"""
Único ponto que muda o andamento de uma regravação, lança no Financeiro e grava o histórico.

Lançamento (`lancar`): quando a regravação está CONCLUÍDA (data do serviço + técnico) e RECEBIDA (forma + data), cria,
numa transação atômica, o Atendimento concluído e pago e o Recebimento (um atendimento só, com o valor total).
Idempotente: acontece uma vez só, mesmo com cliques repetidos ou duas abas. Reabrir estorna (nunca apaga).
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

from .models import AnexoRegravacao, ConfiguracaoEmpresa, HistoricoRegravacao, RegistroRegravacao

Tipo = HistoricoRegravacao.Tipo
Situacao = RegistroRegravacao.Situacao


# ---------- Histórico ----------
def estado(r):
    """Foto do que interessa ao histórico, para comparar antes/depois de uma edição."""
    data = lambda d: f"{d:%d/%m/%Y}" if d else "—"
    return {
        "serviço": r.servicos_texto,
        "valor": reais(r.valor) if r.valor is not None else "—",
        "parceiro": r.parceiro.nome if r.parceiro_id else "—",
        "técnico": r.tecnico.nome if r.tecnico_id else "—",
        "data agendada": data(r.data_agendada),
        "data concluída": data(r.data_concluida),
        "recebimento": (f"{r.get_recebimento_situacao_display()}"
                        + (f" ({r.get_forma_pagamento_display()}, {data(r.data_recebimento)})"
                           if r.recebimento_situacao == Situacao.RECEBIDO else "")),
        "status": r.status_texto,
    }


def _gravar(r, tipo, anterior, novo, usuario):
    HistoricoRegravacao.objects.create(registro=r, tipo=tipo, valor_anterior=anterior, valor_novo=novo, usuario=usuario)


def registrar_criacao(r, usuario):
    _gravar(r, Tipo.CRIACAO, "", f"Regravação criada ({r.placa}; {r.servicos_texto})", usuario)


def registrar_edicao(r, antes, usuario):
    depois = estado(r)
    for campo, anterior in antes.items():
        if depois[campo] != anterior:
            tipo = (Tipo.STATUS if campo == "status" else Tipo.RECEBIMENTO if campo == "recebimento" else Tipo.EDICAO)
            _gravar(r, tipo, f"{campo}: {anterior}", f"{campo}: {depois[campo]}", usuario)


def registrar_documento(r, texto, usuario):
    _gravar(r, Tipo.DOCUMENTO, "", texto, usuario)


# ---------- Anexos ----------
@transaction.atomic
def salvar_anexos(r, novos, remover, usuario):
    """
    novos: {tipo: dict de anexos.processar()}; remover: conjunto de tipos. Trocar = enviar outro do mesmo tipo.
    Arquivos antigos só saem do armazenamento depois que a transação confirma.
    """
    existentes = {a.tipo: a for a in r.anexos.all()}
    apagar, adicionados, removidos = [], 0, 0
    for tipo in remover:
        anexo = existentes.get(tipo)
        if anexo and tipo not in novos:
            apagar += [(anexo.arquivo.storage, anexo.arquivo.name)]
            if anexo.miniatura:
                apagar.append((anexo.miniatura.storage, anexo.miniatura.name))
            _gravar(r, Tipo.ANEXO, anexo.get_tipo_display(), "anexo removido", usuario)
            anexo.delete()
            removidos += 1
    for tipo, dados in novos.items():
        anterior = existentes.get(tipo)
        if anterior:
            apagar += [(anterior.arquivo.storage, anterior.arquivo.name)]
            if anterior.miniatura:
                apagar.append((anterior.miniatura.storage, anterior.miniatura.name))
            anterior.delete()
        anexo = AnexoRegravacao(
            registro=r, tipo=tipo, content_type=dados["content_type"], tamanho=len(dados["conteudo"]),
            nome_original=dados["nome_original"], enviado_por=usuario)
        extensao = "pdf" if dados["content_type"] == "application/pdf" else "jpg"
        nome = uuid.uuid4().hex                      # nome aleatório: não revela placa, cliente nem tipo
        anexo.arquivo.save(f"{nome}.{extensao}", ContentFile(dados["conteudo"]), save=False)
        if dados["miniatura"]:
            anexo.miniatura.save(f"{nome}.jpg", ContentFile(dados["miniatura"]), save=False)
        anexo.save()
        _gravar(r, Tipo.ANEXO, "", f"{anexo.get_tipo_display()} anexado", usuario)
        adicionados += 1

    def limpar():
        for armazenamento, nome in apagar:
            try:
                armazenamento.delete(nome)
            except Exception:
                pass

    transaction.on_commit(limpar)
    return adicionados, removidos


# ---------- Financeiro ----------
def _veiculo(r):
    """O Veículo da mesma placa (de qualquer cliente) ou um novo, em nome do cliente da regravação."""
    veiculo = Veiculo.objects.filter(placa=r.placa).first()
    if veiculo:
        return veiculo
    faltam = [txt for txt, ok in (("a marca", r.marca), ("o modelo", r.modelo), ("o ano/modelo", r.ano_modelo),
                                  ("a cor", r.cor and (r.cor != "outra" or r.cor_outra))) if not ok]
    if faltam:
        raise ValidationError(
            f"Para lançar no Financeiro, preencha {', '.join(faltam)} do veículo (necessários para cadastrá-lo).")
    return Veiculo.objects.create(
        placa=r.placa, marca=r.marca, modelo=r.modelo[:80], ano=int(r.ano_modelo.split("/")[1]), cor=r.cor_texto[:30],
        chassi=r.chassi, proprietario=r.cliente,
        observacoes=f"Cadastrado automaticamente pela regravação #{r.pk}.")


@transaction.atomic
def lancar(registro, usuario):
    """Lança no Financeiro se estiver concluída e recebida. Devolve True se lançou agora (False: nada a fazer)."""
    r = RegistroRegravacao.objects.select_for_update().select_related("cliente", "tecnico").get(pk=registro.pk)
    if r.lancado or r.cancelada:
        return False
    if r.status != RegistroRegravacao.Status.CONCLUIDA or r.recebimento_situacao != Situacao.RECEBIDO:
        return False
    servico = ConfiguracaoEmpresa.obter().servico_para(r.servico_motor, r.servico_chassi)
    if servico is None:
        raise ValidationError(
            "Defina, na aba Empresa, qual tipo de serviço de Regravação vale para este caso "
            f"({r.servicos_texto.lower()}); ele é usado no Financeiro e no Dashboard.")
    if not r.valor or r.valor <= 0:
        raise ValidationError("Informe o valor (maior que zero) para lançar o recebimento no Financeiro.")
    financeiro.exigir_mes_aberto(r.data_recebimento, acao="lançar o recebimento da regravação")
    veiculo = _veiculo(r)

    valor = centavos(r.valor)
    if r.atendimento_id:             # reaberta antes: reaproveita o atendimento, sem criar outro
        a = Atendimento.objects.select_for_update().get(pk=r.atendimento_id)
        antes = historico_atendimento.estado(a)
        a.status, a.valor_cobrado, a.desconto, a.data_atendimento, a.tipo_servico = (
            Atendimento.Status.CONCLUIDO, valor, ZERO, r.data_concluida, servico)
        a.save()
        historico_atendimento.registrar_mudancas(a, antes, usuario)
    else:
        a = Atendimento.objects.create(
            cliente=r.cliente, tipo_servico=servico, veiculo=veiculo, data_atendimento=r.data_concluida,
            valor_cobrado=valor, desconto=ZERO, status=Atendimento.Status.CONCLUIDO,
            observacoes=f"Gerado pela regravação #{r.pk}.", registrado_por=usuario)
        historico_atendimento.registrar_criacao(a, usuario)
    financeiro.registrar_recebimento(a, valor, r.data_recebimento, r.forma_pagamento, f"Regravação #{r.pk}", usuario)

    r.atendimento, r.lancado_em, r.alterado_por = a, timezone.now(), usuario
    r.save(update_fields=["atendimento", "lancado_em", "alterado_por", "alterado_em"])
    _gravar(r, Tipo.FINANCEIRO, "", f"Lançado no Financeiro: {reais(valor)} (atendimento #{a.pk})", usuario)
    registro.__dict__.update(r.__dict__)
    return True


@transaction.atomic
def reabrir(registro, usuario):
    """Estorna o recebimento (fica registrado), reabre o atendimento e volta a regravação para "não concluída"."""
    r = RegistroRegravacao.objects.select_for_update().get(pk=registro.pk)
    if not r.lancado:
        raise ValidationError("Esta regravação não está lançada no Financeiro.")
    a = r.atendimento
    recebimentos = list(a.recebimentos.validos())
    financeiro.exigir_mes_aberto(*[x.data for x in recebimentos], acao="reabrir (estornar o recebimento)")
    for recebimento in recebimentos:
        financeiro.estornar_recebimento(recebimento, f"Reabertura da regravação #{r.pk}", usuario)
    a.refresh_from_db()
    antes = historico_atendimento.estado(a)
    a.status = Atendimento.Status.EM_ANDAMENTO
    a.save(update_fields=["status", "atualizado_em"])
    historico_atendimento.registrar_mudancas(a, antes, usuario)

    r.lancado_em, r.data_concluida, r.recebimento_situacao, r.alterado_por = None, None, Situacao.PENDENTE, usuario
    r.save()
    _gravar(r, Tipo.REABERTURA, "Concluída e recebida",
            f"Reaberta (recebimento estornado; atendimento #{a.pk} reaberto)", usuario)
    registro.__dict__.update(r.__dict__)
    return r


@transaction.atomic
def cancelar(registro, motivo, usuario):
    r = RegistroRegravacao.objects.select_for_update().get(pk=registro.pk)
    if r.lancado:
        raise ValidationError("Esta regravação já foi lançada no Financeiro. Reabra antes de cancelar.")
    motivo = (motivo or "").strip()
    if len(motivo) < 3:
        raise ValidationError("Informe o motivo do cancelamento.")
    antes = estado(r)
    r.cancelada, r.motivo_cancelamento, r.alterado_por = True, motivo[:200], usuario
    r.save()
    registrar_edicao(r, antes, usuario)
    _gravar(r, Tipo.STATUS, "", f"Cancelada: {motivo}", usuario)
    registro.__dict__.update(r.__dict__)
    return r


@transaction.atomic
def registrar_andamento(registro, usuario, data_concluida=None, tecnico=None, situacao=None, forma="", data_recebimento=None):
    """
    Ação "Concluir / receber": grava a data do serviço, o técnico e o recebimento e lança no Financeiro se for o caso.
    Campos em branco não apagam o que já existe.
    """
    r = RegistroRegravacao.objects.select_for_update().select_related("parceiro", "tecnico").get(pk=registro.pk)
    if r.cancelada:
        raise ValidationError("Regravação cancelada não pode ser concluída.")
    antes = estado(r)
    if data_concluida:
        r.data_concluida = data_concluida
    if tecnico:
        r.tecnico = tecnico
    if situacao:
        r.recebimento_situacao = situacao
        if situacao == Situacao.RECEBIDO:
            r.forma_pagamento = forma or r.forma_pagamento
            r.data_recebimento = data_recebimento or r.data_recebimento or timezone.localdate()
    r.alterado_por = usuario
    r.full_clean()
    r.save()
    registrar_edicao(r, antes, usuario)
    lancar(r, usuario)
    registro.__dict__.update(r.__dict__)
    return r
