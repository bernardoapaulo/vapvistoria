from datetime import datetime, timedelta

from django.utils import timezone

from agenda.models import Agendamento
from atendimentos.tests.base import BaseAtendimentoTest


def aware(ano, mes, dia, hora=0, minuto=0):
    """Datetime com fuso America/Sao_Paulo (o fuso do projeto)."""
    return timezone.make_aware(datetime(ano, mes, dia, hora, minuto))


class BaseAgendaTest(BaseAtendimentoTest):
    """Reaproveita usuários e cadastros dos testes de atendimento e acrescenta helpers da agenda."""

    # 07/01/2030 é uma segunda-feira (a empresa abre das 8h às 18h nesse dia).
    SEGUNDA = (2030, 1, 7)

    def momento(self, hora, minuto=0, dia=SEGUNDA):
        return aware(*dia, hora, minuto)

    def agendar(self, inicio=None, minutos=60, atendimento=None, **extra):
        """Cria um agendamento direto no banco (sem passar pelo formulário)."""
        inicio = inicio or self.momento(10)
        dados = dict(
            atendimento=atendimento or self.criar(), inicio=inicio,
            fim=inicio + timedelta(minutes=minutos), criado_por=self.admin,
        )
        dados.update(extra)
        return Agendamento.objects.create(**dados)

    def dados_form(self, **extra):  # noqa: D401 - dados POST de um agendamento válido
        inicio = self.momento(10)
        dados = {
            "atendimento": self.criar().pk,
            "inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
            "fim": (inicio + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "local": "empresa", "detalhe_local": "", "responsavel": "", "observacoes": "",
        }
        dados.update(extra)
        return {k: v for k, v in dados.items() if v is not None}
