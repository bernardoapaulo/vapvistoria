from datetime import date
from decimal import Decimal

from atendimentos.tests.base import BaseAtendimentoTest
from dashboard import periodos
from financeiro import regras
from financeiro.models import CategoriaDespesa, Despesa

MARCO = periodos.Periodo(periodos.PERSONALIZADO, date(2025, 3, 1), date(2025, 3, 31))
HOJE_FICTICIO = date(2025, 4, 20)  # "hoje" usado nas faixas de atraso e na projeção


def d(dia, mes=3, ano=2025):
    return date(ano, mes, dia)


class BaseFinanceiroTest(BaseAtendimentoTest):
    """
    Conjunto pequeno de dados, com os resultados calculados à mão (março/2025, regime de caixa):

      A1 vistoria concluída 05/03   250 - 50 = 200   recebido 200 Pix em 05/03          (pago à vista)
      A2 vistoria concluída 10/03   250              recebido 100 + 100 crédito 10/03 e 15/03 (parcial; saldo 50)
      A3 limpeza  concluída 12/03   100              nada recebido                        (pendente; saldo 100)
      A4 curso    concluído 15/03   900              recebido 900 transferência em 20/03
      B1 vistoria concluída 10/02   250              recebido 250 Pix em 12/02            (período anterior)
      A5 limpeza  solicitado 18/04   80   A6 limpeza solicitado 25/04  70   A7 limpeza concluída 15/01  120
      (A5, A6 e A7 não recebidos: servem às faixas de "a receber")

      Despesas:  D1 Aluguel 1000 venc 05/03 paga 05/03 (geral)    D2 Material 60 venc 10/03 paga 11/03 (direta: limpeza)
                 D3 Luz 200 venc 25/03 em aberto (geral)           D4 Aluguel 1000 venc/pg 05/02 (anterior)
                 D5 150 venc 20/04   D6 90 venc 25/04   D7 300 venc 15/05   D8 500 venc 10/07  (todas em aberto)

    Março, caixa: recebido 1300, despesas pagas 1060, resultado 240, margem 18,5%.
    """

    def setUp(self):
        self.a1 = self.criar(status="concluido", data_atendimento=d(5), desconto=Decimal("50"))
        self.r1 = self.receber(self.a1, data=d(5))
        self.a2 = self.criar(status="concluido", data_atendimento=d(10))
        self.r2a = self.receber(self.a2, "100", "cartao_credito", d(10))
        self.r2b = self.receber(self.a2, "100", "cartao_credito", d(15))
        self.a3 = self.criar(status="concluido", data_atendimento=d(12), cliente=self.outro_cliente,
                             veiculo=self.veiculo_outro, tipo_servico=self.limpeza, valor_cobrado=Decimal("100"))
        self.a4 = self.criar(status="concluido", data_atendimento=d(15), tipo_servico=self.curso, veiculo=None,
                             aluno=self.aluno, valor_cobrado=Decimal("900"))
        self.r4 = self.receber(self.a4, forma="transferencia", data=d(20))
        self.b1 = self.criar(status="concluido", data_atendimento=d(10, 2))
        self.receber(self.b1, forma="pix", data=d(12, 2))

        limpa = dict(cliente=self.outro_cliente, veiculo=self.veiculo_outro, tipo_servico=self.limpeza)
        self.a5 = self.criar(status="solicitado", data_atendimento=d(18, 4), valor_cobrado=Decimal("80"), **limpa)
        self.a6 = self.criar(status="solicitado", data_atendimento=d(25, 4), valor_cobrado=Decimal("70"), **limpa)
        self.a7 = self.criar(status="concluido", data_atendimento=d(15, 1), valor_cobrado=Decimal("120"), **limpa)

        self.cat = {c.nome: c for c in CategoriaDespesa.objects.all()}
        self.d1 = self.despesa("Aluguel", 1000, d(5), d(5))
        self.d2 = self.despesa("Material de limpeza", 60, d(10), d(11), tipo_servico=self.limpeza)
        self.d3 = self.despesa("Água/Luz/Internet", 200, d(25))
        self.d4 = self.despesa("Aluguel", 1000, d(5, 2), d(5, 2))
        self.d5 = self.despesa("Outros", 150, d(20, 4))
        self.d6 = self.despesa("Outros", 90, d(25, 4))
        self.d7 = self.despesa("Outros", 300, d(15, 5))
        self.d8 = self.despesa("Outros", 500, d(10, 7))

    def despesa(self, categoria, valor, vencimento, pagamento=None, **extra):
        dados = dict(descricao=f"Despesa {categoria}", categoria=self.cat[categoria], valor=Decimal(valor),
                     vencimento=vencimento, data_pagamento=pagamento,
                     forma_pagamento="pix" if pagamento else "", criado_por=self.admin)
        dados.update(extra)
        return Despesa.objects.create(**dados)

    def recarregar(self, *objetos):
        for o in objetos:
            o.refresh_from_db()


__all__ = ["BaseFinanceiroTest", "MARCO", "HOJE_FICTICIO", "d", "regras"]
