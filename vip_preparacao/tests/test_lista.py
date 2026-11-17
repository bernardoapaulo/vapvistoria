from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import Atendimento
from financeiro.models import Recebimento
from vip_preparacao.dados_ficticios import gerar_registros_vip
from vip_preparacao.models import FotoVip, RegistroVip

from .base import BaseVipTest


def placas(resposta):
    return [r.placa for r in resposta.context["object_list"]]


class ListaTest(BaseVipTest):
    def setUp(self):
        super().setUp()
        self.a = self.registro(placa="AAA1A11", modelo="Argo", data_preparacao=self.dias(-5))
        self.b = self.registro(placa="BBB2B22", modelo="Onix", cliente=self.outro_cliente, servico=self.preparacao,
                               data_preparacao=self.dias(-3), nota_fiscal="NF-900", valor=Decimal("300.00"))
        self.c = self.registro(placa="CCC3C33", data_preparacao=self.dias(-9))
        self.concluir(self.c)
        self.client.force_login(self.admin)

    def get(self, **params):
        return self.client.get(reverse("vip_lista"), params)

    def test_por_padrao_mostra_so_em_andamento_na_ordem_da_preparacao(self):
        self.assertEqual(placas(self.get()), ["BBB2B22", "AAA1A11"])

    def test_filtro_de_status(self):
        self.assertEqual(placas(self.get(status="concluido")), ["CCC3C33"])
        self.assertEqual(sorted(placas(self.get(status="todos"))), ["AAA1A11", "BBB2B22", "CCC3C33"])

    def test_busca_por_placa_modelo_cliente_e_nota_fiscal(self):
        self.assertEqual(placas(self.get(q="bbb-2b22", status="todos")), ["BBB2B22"])      # placa com hífen e minúsculas
        self.assertEqual(sorted(placas(self.get(q="Argo", status="todos"))), ["AAA1A11", "CCC3C33"])
        self.assertEqual(placas(self.get(q="João", status="todos")), ["BBB2B22"])           # cliente
        self.assertEqual(placas(self.get(q="NF-900", status="todos")), ["BBB2B22"])

    def test_filtros_por_cliente_e_servico(self):
        self.assertEqual(placas(self.get(cliente=self.outro_cliente.pk, status="todos")), ["BBB2B22"])
        self.assertEqual(placas(self.get(servico=self.preparacao.pk, status="todos")), ["BBB2B22"])

    def test_filtro_de_periodo_escolhendo_a_data(self):
        de = self.dias(-6).isoformat()
        self.assertEqual(sorted(placas(self.get(campo_data="data_preparacao", de=de, status="todos"))), ["AAA1A11", "BBB2B22"])
        self.assertEqual(placas(self.get(campo_data="data_preparacao", ate=self.dias(-8).isoformat(), status="todos")), ["CCC3C33"])
        self.registro(placa="DDD4D44", data_devolucao=self.dias(10))
        self.assertEqual(placas(self.get(campo_data="data_devolucao", de=self.dias(9).isoformat(), status="todos")), ["DDD4D44"])

    def test_ordenacao(self):
        self.assertEqual(placas(self.get(ordem="placa", status="todos")), ["AAA1A11", "BBB2B22", "CCC3C33"])
        self.assertEqual(placas(self.get(ordem="-valor", status="todos"))[0], "BBB2B22")

    def test_data_invalida_na_url_nao_quebra(self):
        self.assertEqual(self.get(de="lixo", status="todos").status_code, 200)

    def test_estado_vazio_com_texto_util(self):
        RegistroVip.objects.update(status="concluido")
        resposta = self.get()
        self.assertContains(resposta, "Nenhum registro encontrado em andamento")
        self.assertContains(resposta, "Cadastrar em")

    def test_atrasado_aparece_com_texto_e_destaque(self):
        self.registro(placa="ATR1A23", data_preparacao=self.dias(-8), data_devolucao=self.dias(-2))
        html = self.get().content.decode()
        self.assertIn("Devolução atrasada", html)
        self.assertIn("linha--atrasada", html)

    def test_botao_de_concluir_so_para_quem_pode_e_registro_aberto(self):
        html = self.get().content.decode()
        self.assertEqual(html.count("data-concluir data-url"), 2)           # A e B (C já concluído)


class EtapaTest(BaseVipTest):
    """O filtro de etapa (consulta) tem de concordar com a propriedade `etapa` (Python) em todos os casos."""

    def test_filtro_concorda_com_a_propriedade_para_todas_as_combinacoes_de_datas(self):
        d = self.dias
        casos = [(d(2), None, None), (d(-1), None, None), (d(0), None, None), (d(-5), d(-1), None), (d(-5), d(0), None),
                 (d(-5), d(3), None), (d(-9), d(-4), d(0)), (d(-9), None, d(0)), (d(-9), d(-4), d(-1)), (d(-9), None, d(-3)),
                 (d(-9), d(-4), d(2)), (d(-9), None, d(2))]
        for i, (prep, vip, dev) in enumerate(casos):
            self.registro(placa=f"ETA{i % 10}A{i:02d}", data_preparacao=prep, data_vip=vip, data_devolucao=dev)
        concluido = self.registro(placa="CON1A23")
        self.concluir(concluido)
        self.client.force_login(self.admin)
        for etapa, _ in RegistroVip.Etapa.choices:
            esperado = {r.pk for r in RegistroVip.objects.all() if r.etapa == etapa}
            obtido = {r.pk for r in self.client.get(reverse("vip_lista"), {"etapa": etapa, "status": "todos"}).context["object_list"]}
            self.assertEqual(obtido, esperado, etapa)

    def test_etapas_pelas_datas(self):
        d = self.dias
        Etapa = RegistroVip.Etapa
        self.assertEqual(self.registro(data_preparacao=d(2)).etapa, Etapa.AGUARDANDO)
        self.assertEqual(self.registro(data_preparacao=d(0)).etapa, Etapa.PREPARACAO)
        self.assertEqual(self.registro(data_preparacao=d(-3), data_vip=d(-1)).etapa, Etapa.VIP)
        self.assertEqual(self.registro(data_preparacao=d(-3), data_vip=d(-1), data_devolucao=d(0)).etapa, Etapa.PRONTO)
        self.assertEqual(self.registro(data_preparacao=d(-3), data_devolucao=d(-1)).etapa, Etapa.ATRASADA)
        self.assertTrue(self.registro(data_preparacao=d(-3), data_devolucao=d(-1)).atrasado)


class ConsultasTest(BaseVipTest):
    def test_lista_nao_faz_uma_consulta_por_linha(self):
        for i in range(12):
            self.registro(placa=f"QRY{i % 10}A{i:02d}")
        self.client.force_login(self.admin)
        with CaptureQueriesContext(connection) as q:
            self.client.get(reverse("vip_lista"))
        self.assertLess(len(q), 14, [x["sql"][:80] for x in q])


class DadosFicticiosTest(BaseVipTest):
    def test_gera_15_registros_com_mistura_de_etapas_atrasados_e_concluidos(self):
        for i in range(5):
            from cadastros.models import Cliente
            Cliente.objects.create(nome=f"Cliente {i}", telefone="1")
        criados = gerar_registros_vip([self.admin])
        self.assertEqual(criados, 15)
        registros = list(RegistroVip.objects.all())
        etapas = {r.etapa for r in registros}
        self.assertTrue({"aguardando", "preparacao", "vip", "pronto", "atrasada", "concluido"} <= {str(e) for e in etapas})
        concluidos = [r for r in registros if r.concluido]
        self.assertGreaterEqual(len(concluidos), 3)
        for r in concluidos:               # concluídos: um atendimento pago e um recebimento por item; a soma fecha com o total
            self.assertEqual(r.atendimentos.count(), len(r.lista_itens))
            for item in r.lista_itens:
                self.assertEqual(item.atendimento.situacao_pagamento, "pago")
                (rec,) = item.atendimento.recebimentos.validos()
                self.assertEqual(rec.valor, item.valor)
            self.assertEqual(sum(x.valor for a in r.atendimentos for x in a.recebimentos.validos()), r.valor)
        self.assertEqual({len(r.lista_itens) for r in registros}, {1, 2, 3})
        self.assertGreater(FotoVip.objects.count(), 20)
        self.assertEqual(gerar_registros_vip([self.admin]), 0)                 # não duplica
        self.assertEqual(RegistroVip.objects.count(), 15)

    def test_refazer_apaga_tambem_o_que_foi_gerado_na_conclusao(self):
        from cadastros.models import Cliente
        Cliente.objects.create(nome="Cliente X", telefone="1")
        gerar_registros_vip([self.admin])
        antes = Atendimento.objects.count()
        gerar_registros_vip([self.admin], refazer=True)
        self.assertEqual(Atendimento.objects.count(), antes)               # sem acumular atendimentos
        itens_concluidos = sum(len(r.lista_itens) for r in RegistroVip.objects.concluidos().prefetch_related('itens'))
        self.assertEqual(Recebimento.objects.count(), itens_concluidos)
