"""
Testa a conversão dos pagamentos da etapa 2 (campos do Atendimento) em Recebimentos, usando o
estado REAL do banco antes da migração (atendimentos 0004 + financeiro 0002) com dados antigos.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from financeiro.migracao_pagamentos import CATEGORIAS_PADRAO, converter_pagamentos

ANTES = [("atendimentos", "0004_pagamento_a_revisar"), ("financeiro", "0002_categorias_e_conversao")]
D = Decimal


class ConversaoDosPagamentosAntigosTest(TransactionTestCase):
    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(ANTES)  # volta ao banco como era na etapa 2 (com forma e data de pagamento no atendimento)
        self.apps = executor.loader.project_state(ANTES).apps
        self.addCleanup(self._voltar_ao_atual)

    @staticmethod
    def _voltar_ao_atual():
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _atendimento(self, **campos):
        A = self.apps.get_model("atendimentos", "Atendimento")
        Cliente, Veiculo = self.apps.get_model("cadastros", "Cliente"), self.apps.get_model("cadastros", "Veiculo")
        Tipo = self.apps.get_model("servicos", "TipoServico")
        cliente = Cliente.objects.first() or Cliente.objects.create(nome="Maria", telefone="1")
        veiculo = Veiculo.objects.first() or Veiculo.objects.create(
            placa="ABC1234", marca="Fiat", modelo="Uno", ano=2012, cor="Branco", proprietario=cliente)
        tipo = Tipo.objects.first() or Tipo.objects.create(nome="Vistoria", categoria="vistoria_cautelar", valor_padrao="250")
        dados = dict(cliente=cliente, tipo_servico=tipo, veiculo=veiculo, valor_cobrado=D("250.00"), desconto=D("0.00"),
                     data_atendimento=date(2025, 3, 1), status="concluido", situacao_pagamento="pendente",
                     valor_pago=D("0.00"), forma_pagamento="", data_pagamento=None)
        dados.update(campos)
        return A.objects.create(**dados)

    def test_converte_pago_e_parcial_e_sinaliza_o_que_nao_da_para_saber(self):
        pago = self._atendimento(desconto=D("50.00"), situacao_pagamento="pago", valor_pago=D("200.00"),
                                 forma_pagamento="pix", data_pagamento=date(2025, 3, 5))
        parcial = self._atendimento(situacao_pagamento="parcial", valor_pago=D("100.00"),
                                    forma_pagamento="dinheiro", data_pagamento=date(2025, 3, 10))
        parcial_sem_valor = self._atendimento(situacao_pagamento="parcial", valor_pago=D("0.00"),
                                              forma_pagamento="dinheiro", data_pagamento=date(2025, 3, 11))
        pago_sem_forma = self._atendimento(situacao_pagamento="pago", valor_pago=D("250.00"),
                                           forma_pagamento="", data_pagamento=date(2025, 3, 12))
        pendente = self._atendimento()

        criados, a_revisar = converter_pagamentos(self.apps)
        self.assertEqual((criados, a_revisar), (2, 2))

        Recebimento = self.apps.get_model("financeiro", "Recebimento")
        A = self.apps.get_model("atendimentos", "Atendimento")
        r = Recebimento.objects.get(atendimento_id=pago.pk)
        self.assertEqual((r.valor, r.data, r.forma), (D("200.00"), date(2025, 3, 5), "pix"))
        r = Recebimento.objects.get(atendimento_id=parcial.pk)
        self.assertEqual((r.valor, r.data, r.forma), (D("100.00"), date(2025, 3, 10), "dinheiro"))

        a = A.objects.get(pk=pago.pk)
        self.assertEqual((a.situacao_pagamento, a.valor_pago, a.revisar_pagamento), ("pago", D("200.00"), False))
        a = A.objects.get(pk=parcial.pk)
        self.assertEqual((a.situacao_pagamento, a.valor_pago, a.revisar_pagamento), ("parcial", D("100.00"), False))

        # nada é inventado: sem recebimento, volta a pendente e fica marcado para revisão
        for sem_dados in (parcial_sem_valor, pago_sem_forma):
            self.assertFalse(Recebimento.objects.filter(atendimento_id=sem_dados.pk).exists())
            a = A.objects.get(pk=sem_dados.pk)
            self.assertEqual((a.situacao_pagamento, a.valor_pago, a.revisar_pagamento), ("pendente", D("0.00"), True))

        a = A.objects.get(pk=pendente.pk)
        self.assertEqual((a.situacao_pagamento, a.revisar_pagamento), ("pendente", False))
        self.assertEqual(Recebimento.objects.count(), 2)

    def test_soma_dos_recebimentos_fecha_com_o_valor_pago(self):
        for i in range(3):
            self._atendimento(situacao_pagamento="pago", valor_pago=D("250.00"), forma_pagamento="pix",
                              data_pagamento=date(2025, 3, 1 + i))
        converter_pagamentos(self.apps)
        from django.db.models import Sum
        Recebimento = self.apps.get_model("financeiro", "Recebimento")
        self.assertEqual(Recebimento.objects.aggregate(t=Sum("valor"))["t"], D("750.00"))

    def test_categorias_padrao_foram_criadas_pela_migracao(self):
        Categoria = self.apps.get_model("financeiro", "CategoriaDespesa")
        self.assertEqual(set(Categoria.objects.values_list("nome", flat=True)), set(CATEGORIAS_PADRAO))
