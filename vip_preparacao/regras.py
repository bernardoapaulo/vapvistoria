"""
Único ponto que muda o status do registro VIP/Preparação, lança o recebimento no Financeiro e grava o
histórico. Views e formulários chamam estas funções; nada disso é feito direto nas views.

Conclusão e reabertura são atômicas (transaction.atomic + select_for_update): se qualquer passo falhar
(mês fechado, valor inválido...), nada é gravado.
"""
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from atendimentos import historico as historico_atendimento
from atendimentos.models import Atendimento
from cadastros.models import Veiculo
from financeiro import regras as financeiro
from financeiro.dinheiro import ZERO, centavos, reais

from .models import Cor, FotoVip, HistoricoVip, RegistroVip

Tipo = HistoricoVip.Tipo


# ---------- Histórico ----------
def estado(r):
    """Foto do que interessa ao histórico, para comparar antes/depois de uma edição."""
    data = lambda d: f"{d:%d/%m/%Y}" if d else "—"
    return {
        "valor": reais(r.valor),
        "serviço": r.servico.nome,
        "data de preparação": data(r.data_preparacao),
        "data VIP": data(r.data_vip),
        "data de devolução": data(r.data_devolucao),
        "previsão de pagamento": data(r.previsao_pagamento),
        "nota fiscal": r.nota_fiscal or "—",
    }


def _gravar(r, tipo, anterior, novo, usuario):
    HistoricoVip.objects.create(registro=r, tipo=tipo, valor_anterior=anterior, valor_novo=novo, usuario=usuario)


def registrar_criacao(r, usuario):
    _gravar(r, Tipo.CRIACAO, "", f"Registro criado ({r.placa}, {r.servico.nome}, {reais(r.valor)})", usuario)


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
    Veículo do atendimento: o já cadastrado com a mesma placa (de qualquer cliente: um cliente pode ter
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
def concluir(registro, valor, forma, data_recebimento, usuario, pode_alterar_valor):
    """Conclui o serviço e lança o recebimento. Idempotente: concluir de novo não gera outro recebimento."""
    r = (RegistroVip.objects.select_for_update().select_related("servico", "cliente")
         .get(pk=registro.pk))
    if r.concluido:
        raise ValidationError("Este registro já foi concluído (talvez em outra aba). Atualize a página.")
    faltam = _faltando_para_concluir(r)
    if faltam:
        raise ValidationError(
            f"Para concluir, preencha {', '.join(faltam)} do veículo (botão Editar). "
            "Esses dados são necessários para o cadastro do veículo.")
    if not pode_alterar_valor or valor is None:
        valor = r.valor          # só quem pode alterar o valor muda o que foi combinado
    valor = centavos(valor)
    if valor <= 0:
        raise ValidationError("O valor deve ser maior que zero para lançar o recebimento.")
    data_recebimento = data_recebimento or timezone.localdate()
    financeiro.exigir_mes_aberto(data_recebimento, acao="concluir e lançar o recebimento")

    data_atendimento = r.data_devolucao or data_recebimento
    veiculo = _veiculo(r)
    if r.atendimento_id:     # reaberto antes: reaproveita o mesmo atendimento, sem criar outro
        a = Atendimento.objects.select_for_update().get(pk=r.atendimento_id)
        antes = historico_atendimento.estado(a)
        a.status, a.valor_cobrado, a.desconto, a.data_atendimento = Atendimento.Status.CONCLUIDO, valor, ZERO, data_atendimento
        a.save()
        historico_atendimento.registrar_mudancas(a, antes, usuario)
    else:
        a = Atendimento.objects.create(
            cliente=r.cliente, tipo_servico=r.servico, veiculo=veiculo, data_atendimento=data_atendimento,
            valor_cobrado=valor, desconto=ZERO, status=Atendimento.Status.CONCLUIDO,
            observacoes=f"Gerado pelo registro VIP/Preparação #{r.pk}.", registrado_por=usuario)
        historico_atendimento.registrar_criacao(a, usuario)

    financeiro.registrar_recebimento(a, valor, data_recebimento, forma, f"VIP/Preparação #{r.pk}", usuario)

    anterior = r.valor
    r.valor, r.status, r.atendimento = valor, RegistroVip.Status.CONCLUIDO, a
    r.concluido_em, r.concluido_por, r.alterado_por = timezone.now(), usuario, usuario
    r.save()
    texto = f"Concluído: {reais(valor)} recebido em {data_recebimento:%d/%m/%Y} (atendimento #{a.pk})"
    if anterior != valor:
        texto += f"; valor alterado de {reais(anterior)}"
    _gravar(r, Tipo.CONCLUSAO, "Em andamento", texto, usuario)
    registro.__dict__.update(r.__dict__)
    return r


@transaction.atomic
def reabrir(registro, usuario):
    """Volta para "Em andamento": estorna os recebimentos (ficam registrados) e reabre o atendimento ligado."""
    r = RegistroVip.objects.select_for_update().select_related("atendimento").get(pk=registro.pk)
    if not r.concluido:
        raise ValidationError("Este registro não está concluído.")
    a = r.atendimento
    recebimentos = list(a.recebimentos.validos())
    financeiro.exigir_mes_aberto(*[x.data for x in recebimentos], acao="reabrir (estornar os recebimentos)")
    for recebimento in recebimentos:
        financeiro.estornar_recebimento(
            recebimento, f"Reabertura do registro VIP/Preparação #{r.pk}", usuario)

    a.refresh_from_db()
    antes = historico_atendimento.estado(a)
    a.status = Atendimento.Status.EM_ANDAMENTO
    a.save(update_fields=["status", "atualizado_em"])
    historico_atendimento.registrar_mudancas(a, antes, usuario)

    r.status, r.concluido_em, r.concluido_por, r.alterado_por = RegistroVip.Status.EM_ANDAMENTO, None, None, usuario
    r.save()
    _gravar(r, Tipo.REABERTURA, "Concluído", f"Em andamento (recebimento estornado; atendimento #{a.pk} reaberto)", usuario)
    registro.__dict__.update(r.__dict__)
    return r
