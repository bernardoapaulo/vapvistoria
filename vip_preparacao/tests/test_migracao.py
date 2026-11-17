"""
Migração dos registros antigos (um serviço só) para itens de serviço, em ida e volta, com o estado REAL do banco
antes (vip 0001) e depois (vip 0003): nada de registros, atendimentos e recebimentos pode se perder ou mudar.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

ANTES = [("vip_preparacao", "0001_initial"), ("financeiro", "0002_categorias_e_conversao")]
DEPOIS = [("vip_preparacao", "0003_remove_servico_e_atendimento_do_registro")]
D = Decimal


class MigracaoParaItensTest(TransactionTestCase):
    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(ANTES)                       # banco como era antes dos itens de serviço
        self.apps_antes = executor.loader.project_state(ANTES).apps
        self.addCleanup(self._voltar_ao_atual)

    @staticmethod
    def _voltar_ao_atual():
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _migrar(self, alvo):
        executor = MigrationExecutor(connection)
        executor.migrate(alvo)
        return executor.loader.project_state(alvo).apps

    def _dados_antigos(self):
        a = self.apps_antes
        Cliente, Tipo = a.get_model("cadastros", "Cliente"), a.get_model("servicos", "TipoServico")
        Atendimento, Recebimento = a.get_model("atendimentos", "Atendimento"), a.get_model("financeiro", "Recebimento")
        Registro = a.get_model("vip_preparacao", "RegistroVip")
        cliente = Cliente.objects.create(nome="Maria", telefone="1")
        lavagem = Tipo.objects.create(nome="Lavagem VIP", categoria="limpeza", valor_padrao="150.00")
        reparo = Tipo.objects.create(nome="Reparo", categoria="pequenos_reparos", valor_padrao="300.00")
        atendimento = Atendimento.objects.create(
            cliente=cliente, tipo_servico=lavagem, valor_cobrado=D("150.00"), status="concluido",
            data_atendimento=date(2026, 5, 10), situacao_pagamento="pago", valor_pago=D("150.00"))
        recebimento = Recebimento.objects.create(atendimento=atendimento, valor=D("150.00"), data=date(2026, 5, 10), forma="pix")
        base = dict(cliente=cliente, placa="ABC1D23", marca="Fiat", modelo="Argo", cor="branco", ano=2021,
                    data_preparacao=date(2026, 5, 8))
        concluido = Registro.objects.create(servico=lavagem, valor=D("150.00"), status="concluido", atendimento=atendimento, **base)
        aberto = Registro.objects.create(servico=reparo, valor=D("275.50"), status="em_andamento", **{**base, "placa": "DEF2G34"})
        return dict(cliente=cliente, lavagem=lavagem, reparo=reparo, atendimento=atendimento, recebimento=recebimento,
                    concluido=concluido, aberto=aberto)

    def test_cada_registro_antigo_vira_um_registro_com_um_item_sem_perder_nada(self):
        d = self._dados_antigos()
        novas = self._migrar(DEPOIS)
        Registro, Item = novas.get_model("vip_preparacao", "RegistroVip"), novas.get_model("vip_preparacao", "ItemServicoVip")

        self.assertEqual(Registro.objects.count(), 2)
        self.assertEqual(Item.objects.count(), 2)                                    # 1 item por registro
        concluido = Item.objects.get(registro_id=d["concluido"].pk)
        self.assertEqual((concluido.servico_id, concluido.valor, concluido.atendimento_id),
                         (d["lavagem"].pk, D("150.00"), d["atendimento"].pk))        # serviço, valor e atendimento mantidos
        aberto = Item.objects.get(registro_id=d["aberto"].pk)
        self.assertEqual((aberto.servico_id, aberto.valor, aberto.atendimento_id), (d["reparo"].pk, D("275.50"), None))

        # o total do registro continua o mesmo e os dados dos registros não mudaram
        self.assertEqual(Registro.objects.get(pk=d["concluido"].pk).valor, D("150.00"))
        self.assertEqual(Registro.objects.get(pk=d["aberto"].pk).valor, D("275.50"))
        self.assertEqual(Registro.objects.get(pk=d["concluido"].pk).status, "concluido")
        # atendimentos e recebimentos já lançados ficam exatamente como estavam
        Atendimento, Recebimento = novas.get_model("atendimentos", "Atendimento"), novas.get_model("financeiro", "Recebimento")
        self.assertEqual(Atendimento.objects.count(), 1)
        (rec,) = Recebimento.objects.all()
        self.assertEqual((rec.pk, rec.valor, rec.forma, rec.data, rec.estornado_em), (d["recebimento"].pk, D("150.00"), "pix", date(2026, 5, 10), None))
        # os campos antigos saíram do registro
        nomes = {f.name for f in Registro._meta.get_fields()}
        self.assertNotIn("servico", nomes)
        self.assertNotIn("atendimento", nomes)

    def test_volta_restaura_servico_e_atendimento_do_registro(self):
        d = self._dados_antigos()
        self._migrar(DEPOIS)
        antigas = self._migrar(ANTES)                                                # desfaz tudo
        Registro = antigas.get_model("vip_preparacao", "RegistroVip")
        concluido, aberto = Registro.objects.get(pk=d["concluido"].pk), Registro.objects.get(pk=d["aberto"].pk)
        self.assertEqual((concluido.servico_id, concluido.valor, concluido.atendimento_id), (d["lavagem"].pk, D("150.00"), d["atendimento"].pk))
        self.assertEqual((aberto.servico_id, aberto.valor, aberto.atendimento_id), (d["reparo"].pk, D("275.50"), None))
        self.assertEqual(antigas.get_model("financeiro", "Recebimento").objects.count(), 1)

    def test_ida_volta_ida_e_estavel(self):
        d = self._dados_antigos()
        for _ in range(2):
            novas = self._migrar(DEPOIS)
            self.assertEqual(novas.get_model("vip_preparacao", "ItemServicoVip").objects.count(), 2)
            self._migrar(ANTES)
        self.assertEqual(self.apps_antes.get_model("vip_preparacao", "RegistroVip").objects.count(), 2)
        self.assertEqual(d["concluido"].pk, self.apps_antes.get_model("vip_preparacao", "RegistroVip").objects.get(placa="ABC1D23").pk)
