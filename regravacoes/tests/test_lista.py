from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from regravacoes.dados_ficticios import gerar_regravacoes
from regravacoes.models import RegistroRegravacao

from .base import BaseRegravacaoTest

D = Decimal


def placas(resposta):
    return sorted(r.placa for r in resposta.context["object_list"])


class ListaTest(BaseRegravacaoTest):
    def setUp(self):
        super().setUp()
        from regravacoes.models import Parceiro, Tecnico
        self.p2 = Parceiro.objects.create(nome="Segundo Parceiro")
        self.t2 = Tecnico.objects.create(nome="Segundo Técnico")
        self.a = self.registro(placa="AAA1A11", parceiro=self.parceiro, chassi="9BD11111111111111", servico_motor=True, servico_chassi=False,
                               proprietario="Maria da Placa", valor=D("450.00"))
        self.b = self.registro(placa="BBB2B22", cliente=self.outro_cliente, parceiro=self.p2, data_agendada=self.dias(3), servico_motor=True,
                               servico_chassi=True, valor=D("800.00"), proprietario="Joaquim")
        self.c = self.registro(placa="CCC3C33", data_agendada=self.dias(-5), data_concluida=self.dias(-4), tecnico=self.tecnico,
                               recebimento_situacao="recebido", forma_pagamento="pix", data_recebimento=self.dias(-3))
        self.d = self.registro(placa="DDD4D44", cancelada=True)
        self.client.force_login(self.admin)

    def get(self, **params):
        return self.client.get(reverse("regravacao_lista"), params)

    def test_busca_por_placa_cliente_chassi_proprietario_e_parceiro(self):
        self.assertEqual(placas(self.get(q="bbb-2b22")), ["BBB2B22"])
        self.assertEqual(placas(self.get(q="João")), ["BBB2B22"])                      # cliente
        self.assertEqual(placas(self.get(q="9bd11111111111111")), ["AAA1A11"])         # chassi (minúsculas)
        self.assertEqual(placas(self.get(q="Maria da Placa")), ["AAA1A11"])            # proprietário
        self.assertEqual(placas(self.get(q="Segundo Parceiro")), ["BBB2B22"])          # parceiro

    def test_filtro_de_status_concorda_com_a_propriedade(self):
        for status, _ in RegistroRegravacao.Status.choices:
            esperado = sorted(r.placa for r in RegistroRegravacao.objects.all() if r.status == status)
            self.assertEqual(placas(self.get(status=status)), esperado, status)
        self.assertEqual(placas(self.get(status="concluida")), ["CCC3C33"])
        self.assertEqual(placas(self.get(status="cancelada")), ["DDD4D44"])

    def test_filtros_de_parceiro_tecnico_servico_e_recebimento(self):
        self.assertEqual(placas(self.get(parceiro=self.p2.pk)), ["BBB2B22"])
        self.assertEqual(placas(self.get(tecnico=self.tecnico.pk)), ["CCC3C33"])
        self.assertEqual(placas(self.get(servico="motor")), ["AAA1A11"])
        self.assertEqual(placas(self.get(servico="chassi")), ["CCC3C33", "DDD4D44"])
        self.assertEqual(placas(self.get(servico="ambos")), ["BBB2B22"])
        self.assertEqual(placas(self.get(recebimento="recebido")), ["CCC3C33"])
        self.assertEqual(placas(self.get(recebimento="pendente")), ["AAA1A11", "BBB2B22", "DDD4D44"])

    def test_periodo_escolhendo_a_data(self):
        self.assertEqual(placas(self.get(campo_data="data_agendada", de=self.dias(1).isoformat())), ["BBB2B22"])
        self.assertEqual(placas(self.get(campo_data="data_concluida", ate=self.dias(-4).isoformat())), ["CCC3C33"])
        self.assertEqual(placas(self.get(campo_data="data_recebimento", de=self.dias(-4).isoformat(), ate=self.dias(-2).isoformat())), ["CCC3C33"])
        self.assertEqual(placas(self.get(campo_data="criado_em", de=self.dias(-1).isoformat())), ["AAA1A11", "BBB2B22", "CCC3C33", "DDD4D44"])
        self.assertEqual(self.get(de="lixo").status_code, 200)

    def test_ordenacao(self):
        ordem = lambda o: [r.placa for r in self.get(ordem=o).context["object_list"]]
        self.assertEqual(ordem("placa"), ["AAA1A11", "BBB2B22", "CCC3C33", "DDD4D44"])
        self.assertEqual(ordem("-valor")[0], "BBB2B22")

    def test_indicador_de_documentos_pendentes_com_texto_e_icone(self):
        html = self.get(q="AAA1A11").content.decode()
        self.assertIn("1 pendente", html)                                              # a autorização de motor falta
        self.assertIn('class="icone"', html)
        self.anexar(self.a, "autorizacao_motor")
        self.assertIn("Completos", self.get(q="AAA1A11").content.decode())

    def test_botoes_por_linha_conforme_o_andamento(self):
        html = self.get(q="CCC3C33").content.decode()
        self.assertIn(reverse("documento_emitir", args=[self.c.pk, "declaracao"]), html)             # concluída: Declaração
        self.assertIn(reverse("documento_emitir", args=[self.c.pk, "recibo"]), html)                 # recebida: Recibo
        html = self.get(q="AAA1A11").content.decode()
        self.assertNotIn(reverse("documento_emitir", args=[self.a.pk, "declaracao"]), html)
        self.assertIn("data-concluir-reg", html)

    def test_estado_vazio_com_texto_util(self):
        resposta = self.get(q="nada-aqui")
        self.assertContains(resposta, "Nenhuma regravação encontrada")
        self.assertContains(resposta, "Cadastrar em")

    def test_lista_nao_faz_consulta_por_linha(self):
        for i in range(12):
            self.registro(placa=f"QRY{i % 10}A{i:02d}", parceiro=self.parceiro, tecnico=self.tecnico)
        with CaptureQueriesContext(connection) as q:
            self.get()
        self.assertLess(len(q), 16, [x["sql"][:80] for x in q])

    def test_valor_aparece_formatado_em_reais(self):
        self.assertContains(self.get(q="BBB2B22"), "R$ 800,00")


class DadosFicticiosTest(BaseRegravacaoTest):
    def test_gera_12_regravacoes_com_mistura_de_situacoes(self):
        from cadastros.models import Cliente
        for i in range(4):
            Cliente.objects.create(nome=f"Cliente Fictício {i}", telefone="1")
        criadas = gerar_regravacoes([self.admin])
        self.assertEqual(criadas, 12)
        registros = list(RegistroRegravacao.objects.all())
        self.assertEqual({r.servicos_texto for r in registros}, {"Motor", "Chassi", "Motor e chassi"})
        status = {str(r.status) for r in registros}
        self.assertEqual(status, {"solicitada", "agendada", "concluida", "cancelada"})
        self.assertTrue(any(r.lancado for r in registros))
        self.assertTrue(any(r.recebimento_situacao == "pendente" and r.status == "concluida" for r in registros))
        self.assertTrue(any(r.anexos_pendentes for r in registros))
        self.assertTrue(any(r.documentos.exists() for r in registros))
        self.assertEqual(gerar_regravacoes([self.admin]), 0)                      # não duplica
        antes = RegistroRegravacao.objects.count()
        gerar_regravacoes([self.admin], refazer=True)
        self.assertEqual(RegistroRegravacao.objects.count(), antes)

    def test_nenhum_dado_real_nos_dados_ficticios(self):
        from regravacoes import dados_ficticios
        import inspect
        fonte = inspect.getsource(dados_ficticios)
        for proibido in ("21.433.416", "Antônio Aleixo", "Vap Vistoria Ltda", "MANOEL", "OCZ6B37", "9BC15844"):
            self.assertNotIn(proibido, fonte)
