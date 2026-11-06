"""
Regras que ligam a agenda ao atendimento. Telas e formulários chamam estas
funções; elas mudam o agendamento, o atendimento (pelo módulo
atendimentos/historico.py, que grava a linha do tempo) e anotam o que
aconteceu no histórico do atendimento.
"""
from django.db import transaction
from django.utils import timezone

from atendimentos import historico
from atendimentos.models import Atendimento

from .models import Agendamento

S = Agendamento.Status
StatusAtendimento = Atendimento.Status


class RegraAgenda(Exception):
    """Mudança não permitida. A mensagem já está em português, pronta para a tela."""


def quando(ag):
    ini, fim = timezone.localtime(ag.inicio), timezone.localtime(ag.fim)
    return f"{ini:%d/%m/%Y %H:%M}–{fim:%H:%M}"


def apos_criar(ag, usuario):
    """Atendimento Solicitado passa para Agendado; o histórico guarda os dois fatos."""
    at = ag.atendimento
    historico.registrar_agenda(at, f"Agendamento criado para {quando(ag)}", usuario)
    if at.status == StatusAtendimento.SOLICITADO:
        historico.alterar_status(at, StatusAtendimento.AGENDADO, usuario)


def apos_editar(ag, inicio_antes, fim_antes, usuario):
    if (ag.inicio, ag.fim) != (inicio_antes, fim_antes):
        antes = f"{timezone.localtime(inicio_antes):%d/%m/%Y %H:%M}–{timezone.localtime(fim_antes):%H:%M}"
        historico.registrar_agenda(ag.atendimento, f"Horário alterado de {antes} para {quando(ag)}", usuario)


def outros_ativos(ag):
    """Quantos outros agendamentos ainda pendentes o atendimento tem."""
    return ag.atendimento.agendamentos.ativos().exclude(pk=ag.pk).count()


@transaction.atomic
def mudar_status(ag, novo, usuario, concluir_atendimento=False):
    if not ag.pode_ir_para(novo):
        raise RegraAgenda("Esta mudança de status não é permitida para este agendamento.")
    anterior = ag.get_status_display()
    ag.status = novo
    ag.save(update_fields=["status", "atualizado_em"])
    at = ag.atendimento
    historico.registrar_agenda(at, f"Agendamento de {quando(ag)}: {anterior} → {ag.get_status_display()}", usuario)

    if novo == S.EM_ANDAMENTO and at.status in (StatusAtendimento.SOLICITADO, StatusAtendimento.AGENDADO):
        historico.alterar_status(at, StatusAtendimento.EM_ANDAMENTO, usuario)
    if novo == S.CONCLUIDO and concluir_atendimento and at.pode_ir_para(StatusAtendimento.CONCLUIDO):
        historico.alterar_status(at, StatusAtendimento.CONCLUIDO, usuario)


@transaction.atomic
def remarcar(ag, inicio, fim, usuario):
    """Cria o novo agendamento, marca o antigo como Remarcado e liga os dois."""
    if ag.status not in Agendamento.PODE_REMARCAR:
        raise RegraAgenda("Só é possível remarcar um agendamento Agendado ou Confirmado.")
    if fim <= inicio:
        raise RegraAgenda("O horário de fim deve ser posterior ao horário de início.")
    novo = Agendamento.objects.create(
        atendimento=ag.atendimento, inicio=inicio, fim=fim, local=ag.local, detalhe_local=ag.detalhe_local,
        responsavel=ag.responsavel, observacoes=ag.observacoes, status=S.AGENDADO,
        remarcado_de=ag, criado_por=usuario,
    )
    antigo = quando(ag)
    ag.status = S.REMARCADO
    ag.save(update_fields=["status", "atualizado_em"])
    historico.registrar_agenda(ag.atendimento, f"Agendamento remarcado de {antigo} para {quando(novo)}", usuario)
    return novo
