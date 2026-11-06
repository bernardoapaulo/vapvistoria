from datetime import date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from agenda.models import Agendamento
from atendimentos.models import Atendimento
from atendimentos.tests.base import BaseAtendimentoTest
from dashboard import periodos
from dashboard.services import Filtros

MARCO = periodos.Periodo(periodos.PERSONALIZADO, date(2025, 3, 1), date(2025, 3, 31))


def filtros(periodo=MARCO, **extra):
    return Filtros(periodo, **extra)


class BaseDashboardTest(BaseAtendimentoTest):
    """
    Conjunto pequeno e conhecido de dados (março/2025), com os resultados calculados à mão:

      A1 vistoria  concluído  250 - desc 50 = 200   Maria  05/03
      A2 vistoria  concluído  250                    Maria  10/03
      A3 limpeza   concluído  100                    João   12/03
      A4 curso     concluído  900 (aluno)            Maria  15/03
      A5 vistoria  CANCELADO  250                    Maria  20/03   (nunca entra no faturamento)
      A6 limpeza   em andamento 100                  Maria  25/03   (em aberto vencido)
      B1 vistoria  concluído  250                    Maria  10/02   (período anterior)

    Março: 4 serviços, faturamento 1450,00, ticket médio 362,50.
    """

    def setUp(self):
        d = lambda dia, mes=3: date(2025, mes, dia)  # noqa: E731
        self.a1 = self.criar(status="concluido", data_atendimento=d(5), desconto=Decimal("50"))
        self.receber(self.a1, data=d(5))  # pago em Pix: 250 - 50 = 200
        self.a2 = self.criar(status="concluido", data_atendimento=d(10))
        self.a3 = self.criar(status="concluido", data_atendimento=d(12), cliente=self.outro_cliente,
                             veiculo=self.veiculo_outro, tipo_servico=self.limpeza, valor_cobrado=Decimal("100"))
        self.a4 = self.criar(status="concluido", data_atendimento=d(15), tipo_servico=self.curso, veiculo=None,
                             aluno=self.aluno, valor_cobrado=Decimal("900"))
        self.a5 = self.criar(status="cancelado", data_atendimento=d(20))
        self.a6 = self.criar(status="em_andamento", data_atendimento=d(25), tipo_servico=self.limpeza,
                             valor_cobrado=Decimal("100"))
        self.b1 = self.criar(status="concluido", data_atendimento=d(10, 2))

    def agendar(self, atendimento, inicio, status="agendado", minutos=60, **extra):
        return Agendamento.objects.create(
            atendimento=atendimento, inicio=inicio, fim=inicio + timedelta(minutes=minutos),
            status=status, criado_por=self.admin, **extra)

    @staticmethod
    def hora_local(ano, mes, dia, hora=10, minuto=0):
        return timezone.make_aware(datetime(ano, mes, dia, hora, minuto))


def novo_atendimento_em(testcase, dia, **extra):
    """Atalho: atendimento concluído numa data qualquer."""
    return testcase.criar(status="concluido", data_atendimento=dia, **extra)


__all__ = ["BaseDashboardTest", "MARCO", "filtros", "Atendimento", "novo_atendimento_em"]
