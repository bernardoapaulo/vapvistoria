"""Consultas do painel de Pendências e da página inicial."""
from atendimentos.models import Atendimento

from .models import Agendamento


def solicitados_sem_agendamento():
    """Atendimentos Solicitados que ainda não têm nenhum agendamento ativo."""
    return (
        Atendimento.objects.filter(status=Atendimento.Status.SOLICITADO)
        .exclude(agendamentos__status__in=Agendamento.ATIVOS)
        .select_related("cliente", "tipo_servico", "veiculo", "aluno")
        .order_by("data_atendimento", "id")
    )


def pendencias():
    base = Agendamento.objects.com_detalhes()
    return {
        "hoje": base.hoje(),
        "proximos": base.proximos_dias(7),
        "atrasados": base.atrasados().order_by("inicio"),
        "sem_agendamento": solicitados_sem_agendamento(),
    }


def contar_pendencias():
    """Número mostrado na página inicial: o que pede uma ação (atrasados + sem agendamento)."""
    return Agendamento.objects.atrasados().count() + solicitados_sem_agendamento().count()
