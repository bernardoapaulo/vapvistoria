"""
Único ponto que muda o status do registro VIP/Preparação, os itens de serviço, lança os recebimentos no Financeiro
e grava o histórico. Views e formulários chamam estas funções; nada disso é feito direto nas views.

Cada ITEM de serviço vira um Atendimento concluído (assim o Dashboard por serviço e por categoria fica certo) e cada
atendimento recebe um Recebimento do mesmo valor do item. A soma dos recebimentos é sempre igual ao total do registro.

Conclusão e reabertura são atômicas (transaction.atomic + select_for_update): se qualquer passo falhar
(mês fechado, valor inválido...), nada é gravado.
"""
import uuid
from decimal import ROUND_DOWN, Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from atendimentos import historico as historico_atendimento
from atendimentos.models import Atendimento
from cadastros.models import Veiculo
from financeiro import regras as financeiro
from financeiro.dinheiro import ZERO, centavos, reais

from .models import Cor, FotoVip, HistoricoVip, ItemServicoVip, RegistroVip

Tipo = HistoricoVip.Tipo
CENTAVO = Decimal("0.01")


# ---------- Histórico ----------
def estado(r):
    """Foto do que interessa ao histórico, para comparar antes/depois de uma edição (os itens têm histórico próprio)."""
    data = lambda d: f"{d:%d/%m/%Y}" if d else "—"
    return {
        "data de preparação": data(r.data_preparacao),
        "data VIP": data(r.data_vip),
        "data de devolução": data(r.data_devolucao),
        "previsão de pagamento": data(r.previsao_pagamento),
        "nota fiscal": r.nota_fiscal or "—",
    }


def _gravar(r, tipo, anterior, novo, usuario):
    HistoricoVip.objects.create(registro=r, tipo=tipo, valor_anterior=anterior, valor_novo=novo, usuario=usuario)


def registrar_criacao(r, usuario):
    servicos = ", ".join(i.servico.nome for i in r.itens.select_related("servico")) or "sem serviços"
    _gravar(r, Tipo.CRIACAO, "", f"Registro criado ({r.placa}; {servicos}; total {reais(r.valor)})", usuario)


def registrar_edicao(r, antes, usuario):
    """Uma linha por campo relevante que mudou."""
    for campo, anterior in antes.items():
        atual = estado(r)[campo]
        if atual != anterior:
            _gravar(r, Tipo.EDICAO, f"{campo}: {anterior}", f"{campo}: {atual}", usuario)


def registrar_fotos(r, adicionadas, removidas, usuario):
    partes = []
    if adicionadas:
        partes.append(f"{adicionadas} foto(s) enviada(s)")
    if removidas:
        partes.append(f"{removidas} foto(s) removida(s)")
    if partes:
        _gravar(r, Tipo.FOTOS, "", ", ".join(partes), usuario)


# ---------- Itens de serviço ----------
def recalcular_total(r):
    """Único lugar que grava o total do registro: a soma dos valores dos itens."""
    total = sum((i.valor for i in r.itens.all()), ZERO)
    r.valor = centavos(total)
    r.save(update_fields=["valor", "alterado_em"])
    return r.valor


def ratear(total, valores):
    """
    Divide `total` entre os itens na proporção dos `valores`, em centavos. Cada parte é arredondada para baixo e o
    ÚLTIMO item absorve a diferença, então a soma é exatamente `total`.
    """
    total, soma = centavos(total), sum(valores, ZERO)
    if soma <= 0:
        raise ValidationError("Não é possível ratear: os valores dos itens somam zero.")
    partes = [(total * v / soma).quantize(CENTAVO, rounding=ROUND_DOWN) for v in valores[:-1]]
    partes.append(total - sum(partes, ZERO))
    return partes


def _cancelar_atendimento(item, r, usuario):
    """Item removido de um registro reaberto: o atendimento dele é cancelado (nunca apagado)."""
    a = item.atendimento
    if a and a.status != Atendimento.Status.CANCELADO:
        historico_atendimento.alterar_status(a, Atendimento.Status.CANCELADO, usuario)
        a.observacoes = (a.observacoes + f"\nItem removido do registro VIP/Preparação #{r.pk}.").strip()
        a.save(update_fields=["observacoes", "atualizado_em"])


@transaction.atomic
def salvar_itens(r, entradas, usuario, registrar=True):
    """
    Sincroniza os itens com a lista da tela. `entradas`: [{id, servico, valor, observacao, remover}].
    Registra no histórico cada item adicionado, removido ou alterado (`registrar=False` na criação do registro, onde
    a própria linha "Registro criado" já lista os serviços). Em registro concluído os itens não mudam.
    """
    if r.concluido:
        raise ValidationError("Registro concluído: reabra para alterar os serviços.")
    atuais = {i.pk: i for i in r.itens.select_related("servico", "atendimento")}
    for e in entradas:
        item = atuais.get(e["id"]) if e["id"] else None
        if item and e["remover"]:
            if registrar:
                _gravar(r, Tipo.ITENS, f"{item.servico.nome} ({reais(item.valor)})", "item removido", usuario)
            _cancelar_atendimento(item, r, usuario)
            item.delete()
        elif item:
            mudancas = []
            if item.servico_id != e["servico"].pk:
                mudancas.append(f"serviço {item.servico.nome} → {e['servico'].nome}")
            if item.valor != centavos(e["valor"]):
                mudancas.append(f"valor {reais(item.valor)} → {reais(centavos(e['valor']))}")
            if item.observacao != e["observacao"]:
                mudancas.append("observação alterada")
            if mudancas:
                item.servico, item.valor, item.observacao = e["servico"], centavos(e["valor"]), e["observacao"]
                item.save()
                if registrar:
                    _gravar(r, Tipo.ITENS, item.servico.nome, "; ".join(mudancas), usuario)
        elif not e["remover"]:
            novo = ItemServicoVip.objects.create(
                registro=r, servico=e["servico"], valor=centavos(e["valor"]), observacao=e["observacao"])
            if registrar:
                _gravar(r, Tipo.ITENS, "", f"item adicionado: {novo.servico.nome} ({reais(novo.valor)})", usuario)
    return recalcular_total(r)


# ---------- Fotos ----------
@transaction.atomic
def salvar_fotos(r, novas, remover, usuario):
    """
    novas: {(momento, posicao): (jpeg, miniatura)} já processadas por fotos.processar().
    remover: conjunto de (momento, posicao). Trocar uma foto = enviar outra na mesma posição.
    Arquivos antigos só são apagados do armazenamento depois que a transação confirma.
    """
    existentes = {(f.momento, f.posicao): f for f in r.fotos.all()}
    apagar = []
    adicionadas = removidas = 0
    for chave in remover:
        foto = existentes.get(chave)
        if foto and chave not in novas:
            apagar += [(foto.imagem.storage, foto.imagem.name), (foto.miniatura.storage, foto.miniatura.name)]
            foto.delete()
            removidas += 1
    for (momento, posicao), (grande, mini) in novas.items():
        foto = existentes.get((momento, posicao))
        if foto:
            apagar += [(foto.imagem.storage, foto.imagem.name), (foto.miniatura.storage, foto.miniatura.name)]
            foto.delete()
        nova = FotoVip(registro=r, momento=momento, posicao=posicao, enviado_por=usuario)
        nome = uuid.uuid4().hex
        nova.imagem.save(f"{nome}.jpg", ContentFile(grande), save=False)
        nova.miniatura.save(f"{nome}.jpg", ContentFile(mini), save=False)
        nova.save()
        adicionadas += 1
    registrar_fotos(r, adicionadas, removidas, usuario)

    def limpar():
        for armazenamento, nome in apagar:
            try:
                armazenamento.delete(nome)
            except Exception:  # arquivo já ausente não deve quebrar a resposta
                pass

    transaction.on_commit(limpar)


# ---------- Conclusão e reabertura ----------
def _veiculo(r):
    """
    Veículo dos atendimentos: o já cadastrado com a mesma placa (de qualquer cliente: um cliente pode ter
    vários carros e a placa pode ter outro cadastro) ou um novo, em nome do cliente do registro.
    """
    veiculo = Veiculo.objects.filter(placa=r.placa).first()
    if veiculo:
        return veiculo
    return Veiculo.objects.create(
        placa=r.placa, marca=r.marca, modelo=f"{r.modelo} {r.versao}".strip()[:80], ano=r.ano,
        cor=r.cor_texto[:30], chassi=r.chassi, proprietario=r.cliente,
        observacoes=f"Cadastrado automaticamente ao concluir o registro VIP/Preparação #{r.pk}.")


def _faltando_para_concluir(r):
    faltam = []
    if not r.marca:
        faltam.append("a marca")
    if not r.modelo:
        faltam.append("o modelo")
    if not r.ano:
        faltam.append("o ano")
    if not r.cor or (r.cor == Cor.OUTRA and not r.cor_outra):
        faltam.append("a cor")
    return faltam


@transaction.atomic
def concluir(registro, total, forma, data_recebimento, usuario, pode_alterar_valor):
    """
    Conclui o serviço e lança os recebimentos (um por item). Idempotente: concluir de novo não gera outro recebimento.
    `total` só vale para quem pode alterar o valor: se diferir da soma dos itens, os itens são reajustados em
    proporção (centavos; o último absorve a diferença) e a mudança vai para o histórico.
    """
    r = (RegistroVip.objects.select_for_update().select_related("cliente").get(pk=registro.pk))
    if r.concluido:
        raise ValidationError("Este registro já foi concluído (talvez em outra aba). Atualize a página.")
    faltam = _faltando_para_concluir(r)
    if faltam:
        raise ValidationError(
            f"Para concluir, preencha {', '.join(faltam)} do veículo (botão Editar). "
            "Esses dados são necessários para o cadastro do veículo.")
    itens = list(r.itens.select_related("servico", "atendimento").order_by("id"))
    if not itens:
        raise ValidationError("O registro não tem serviços. Edite e adicione pelo menos um.")

    soma = sum((i.valor for i in itens), ZERO)
    if pode_alterar_valor and total is not None and centavos(total) != soma:
        novos = ratear(total, [i.valor for i in itens])
        for item, valor in zip(itens, novos):
            if valor != item.valor:
                _gravar(r, Tipo.ITENS, f"{item.servico.nome} ({reais(item.valor)})",
                        f"valor ajustado para {reais(valor)} (total alterado na conclusão)", usuario)
                item.valor = valor
                item.save(update_fields=["valor"])
    if any(i.valor <= 0 for i in itens):
        raise ValidationError("Todos os serviços precisam ter valor maior que zero para lançar o recebimento.")

    data_recebimento = data_recebimento or timezone.localdate()
    financeiro.exigir_mes_aberto(data_recebimento, acao="concluir e lançar o recebimento")
    data_atendimento = r.data_devolucao or data_recebimento
    veiculo = _veiculo(r)

    for item in itens:
        if item.atendimento_id:     # registro reaberto antes: reaproveita o atendimento do item, sem criar outro
            a = Atendimento.objects.select_for_update().get(pk=item.atendimento_id)
            antes = historico_atendimento.estado(a)
            a.status, a.valor_cobrado, a.desconto, a.data_atendimento = (
                Atendimento.Status.CONCLUIDO, item.valor, ZERO, data_atendimento)
            a.save()
            historico_atendimento.registrar_mudancas(a, antes, usuario)
        else:
            a = Atendimento.objects.create(
                cliente=r.cliente, tipo_servico=item.servico, veiculo=veiculo, data_atendimento=data_atendimento,
                valor_cobrado=item.valor, desconto=ZERO, status=Atendimento.Status.CONCLUIDO,
                observacoes=f"Gerado pelo registro VIP/Preparação #{r.pk}.", registrado_por=usuario)
            historico_atendimento.registrar_criacao(a, usuario)
            item.atendimento = a
            item.save(update_fields=["atendimento"])
        financeiro.registrar_recebimento(
            a, item.valor, data_recebimento, forma, f"VIP/Preparação #{r.pk} · {item.servico.nome}", usuario)

    anterior = r.valor
    recalcular_total(r)
    r.status, r.concluido_em, r.concluido_por, r.alterado_por = RegistroVip.Status.CONCLUIDO, timezone.now(), usuario, usuario
    r.save()
    texto = (f"Concluído: {reais(r.valor)} recebido em {data_recebimento:%d/%m/%Y} "
             f"({len(itens)} serviço(s), {len(itens)} atendimento(s))")
    if anterior != r.valor:
        texto += f"; total alterado de {reais(anterior)}"
    _gravar(r, Tipo.CONCLUSAO, "Em andamento", texto, usuario)
    registro.__dict__.update(r.__dict__)
    return r


@transaction.atomic
def reabrir(registro, usuario):
    """Volta para "Em andamento": estorna TODOS os recebimentos (ficam registrados) e reabre todos os atendimentos."""
    r = RegistroVip.objects.select_for_update().get(pk=registro.pk)
    if not r.concluido:
        raise ValidationError("Este registro não está concluído.")
    atendimentos = list(r.atendimentos)
    recebimentos = [rec for a in atendimentos for rec in a.recebimentos.validos()]
    financeiro.exigir_mes_aberto(*[x.data for x in recebimentos], acao="reabrir (estornar os recebimentos)")
    for recebimento in recebimentos:
        financeiro.estornar_recebimento(
            recebimento, f"Reabertura do registro VIP/Preparação #{r.pk}", usuario)
    for a in atendimentos:
        a.refresh_from_db()
        antes = historico_atendimento.estado(a)
        a.status = Atendimento.Status.EM_ANDAMENTO
        a.save(update_fields=["status", "atualizado_em"])
        historico_atendimento.registrar_mudancas(a, antes, usuario)

    r.status, r.concluido_em, r.concluido_por, r.alterado_por = RegistroVip.Status.EM_ANDAMENTO, None, None, usuario
    r.save()
    numeros = ", ".join(f"#{a.pk}" for a in atendimentos)
    _gravar(r, Tipo.REABERTURA, "Concluído", f"Em andamento (recebimentos estornados; atendimentos {numeros} reabertos)", usuario)
    registro.__dict__.update(r.__dict__)
    return r
