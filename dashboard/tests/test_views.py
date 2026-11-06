import csv
import io
from datetime import date
from decimal import Decimal

from django.urls import reverse

from .base import BaseDashboardTest

MARCO = {"periodo": "personalizado", "de": "2025-03-01", "ate": "2025-03-31"}


class DashboardPermissoesTest(BaseDashboardTest):
    def _get(self, usuario, **params):
        self.client.force_login(usuario)
        return self.client.get(reverse("dashboard"), params)

    def test_exige_login(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/entrar/", resp.url)

    def test_administrador_recebe_faturamento_e_valores(self):
        resp = self._get(self.admin, **MARCO)
        self.assertEqual(resp.status_code, 200)
        fin = resp.context["financeiro"]
        self.assertEqual(fin["faturamento"], Decimal("1450.00"))
        self.assertEqual(fin["ticket_medio"], Decimal("362.50"))
        self.assertContains(resp, "R$ 1.450,00")
        self.assertContains(resp, "R$ 362,50")
        self.assertContains(resp, "Top 10 clientes por faturamento")
        self.assertContains(resp, "Baixar CSV do período")

    def test_funcionario_nao_recebe_nenhum_dado_financeiro(self):
        resp = self._get(self.func, **MARCO)
        self.assertEqual(resp.status_code, 200)
        # no servidor: a parte financeira nem é calculada nem enviada
        self.assertNotIn("financeiro", resp.context)
        for chave in ("faturamento", "ticket_medio", "a_receber", "top_clientes"):
            self.assertNotIn(chave, resp.context)
        self.assertNotIn("faturamento", resp.context["ranking"][0])
        # e nada de valores no HTML
        html = resp.content.decode()
        for proibido in ("R$", "1.450", "1450", "Faturamento", "Ticket", "A receber", "Top 10 clientes", "Baixar CSV"):
            self.assertNotIn(proibido, html)
        # o que é operacional aparece
        self.assertContains(resp, "Total de serviços")
        self.assertContains(resp, "Taxa de cancelamento")

    def test_funcionario_nao_consegue_exportar_csv(self):
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("dashboard_exportar"), MARCO).status_code, 403)

    def test_anonimo_nao_exporta(self):
        self.assertEqual(self.client.get(reverse("dashboard_exportar")).status_code, 302)

    def test_permissoes_dos_perfis(self):
        self.assertTrue(self.admin.has_perm("atendimentos.ver_faturamento"))
        self.assertTrue(self.admin.has_perm("atendimentos.exportar_dados"))
        self.assertFalse(self.func.has_perm("atendimentos.ver_faturamento"))
        self.assertFalse(self.func.has_perm("atendimentos.exportar_dados"))
        self.assertTrue(self.func.has_perm("atendimentos.view_atendimento"))


class DashboardTelaTest(BaseDashboardTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_indicadores_na_tela(self):
        resp = self.client.get(reverse("dashboard"), MARCO)
        ind = resp.context["indicadores"]
        self.assertEqual((ind["servicos"], ind["alunos_atendidos"]), (4, 1))
        self.assertEqual([(c["rotulo"], c["valor"]) for c in resp.context["categorias"]],
                         [("Vistoria cautelar", 2), ("Regravação", 0), ("Capacitação", 1), ("Limpeza", 1),
                          ("Pequenos reparos", 0)])
        self.assertContains(resp, "+300%")
        self.assertContains(resp, "Como os números são calculados")

    def test_filtros_invalidos_nao_quebram(self):
        for params in ({"periodo": "xx"}, {"categoria": "zz"}, {"responsavel": "abc"},
                       {"periodo": "personalizado", "de": "lixo", "ate": "2025-01-01"}, {}):
            self.assertEqual(self.client.get(reverse("dashboard"), params).status_code, 200)

    def test_periodo_sem_dados_mostra_mensagem_e_zeros(self):
        resp = self.client.get(reverse("dashboard"), {"periodo": "personalizado", "de": "2020-01-01", "ate": "2020-01-31"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sem dados neste período.")
        self.assertEqual(resp.context["indicadores"]["servicos"], 0)
        self.assertEqual(resp.context["financeiro"]["faturamento"], Decimal("0.00"))

    def test_filtro_de_categoria_pela_tela(self):
        resp = self.client.get(reverse("dashboard"), {**MARCO, "categoria": "limpeza"})
        self.assertEqual(resp.context["indicadores"]["servicos"], 1)
        self.assertEqual(resp.context["financeiro"]["faturamento"], Decimal("100.00"))

    def test_graficos_chegam_como_json_para_o_javascript(self):
        html = self.client.get(reverse("dashboard"), MARCO).content.decode()
        self.assertIn('id="g-status"', html)
        self.assertIn('data-grafico="g-status"', html)
        self.assertIn("vendor/chartjs/chart.umd.min.js", html)
        self.assertIn("dashboard.js", html)

    def test_menu_e_pagina_inicial(self):
        resp = self.client.get(reverse("inicio"))
        self.assertContains(resp, reverse("dashboard"))
        self.assertIn("faturamento", resp.context["resumo_mes"])
        self.client.force_login(self.func)
        resp = self.client.get(reverse("inicio"))
        self.assertContains(resp, reverse("dashboard"))
        self.assertNotIn("faturamento", resp.context["resumo_mes"])
        self.assertNotContains(resp, "Faturamento")


class ExportarCsvTest(BaseDashboardTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def _baixar(self, **extra):
        return self.client.get(reverse("dashboard_exportar"), {**MARCO, **extra})

    def test_cabecalhos_e_formato_para_excel_em_portugues(self):
        resp = self._baixar()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("servicos_2025-03-01_a_2025-03-31.csv", resp["Content-Disposition"])
        bruto = resp.content
        self.assertTrue(bruto.startswith("﻿".encode("utf-8")))  # BOM: o Excel reconhece UTF-8
        texto = bruto.decode("utf-8-sig")
        linhas = list(csv.reader(io.StringIO(texto), delimiter=";"))  # ponto e vírgula
        self.assertEqual(linhas[0][:3], ["Data", "Cliente", "Serviço"])
        self.assertEqual(len(linhas), 1 + 4)  # só os 4 concluídos de março
        primeira = linhas[1]
        self.assertEqual(primeira[:8], ["05/03/2025", "Maria Teste", "Vistoria", "Vistoria cautelar",
                                        "250,00", "50,00", "200,00", "Pago"])
        self.assertEqual(primeira[8:], ["200,00", "Pix"])
        self.assertNotIn("20/03/2025", texto)  # cancelado fora
        self.assertNotIn("25/03/2025", texto)  # em andamento fora

    def test_acentos_preservados(self):
        self.a4.cliente.nome = "José Açaí"
        self.a4.cliente.save()
        texto = self._baixar().content.decode("utf-8-sig")
        self.assertIn("José Açaí", texto)
        self.assertIn("Capacitação", texto)

    def test_respeita_filtros(self):
        linhas = list(csv.reader(io.StringIO(self._baixar(categoria="limpeza").content.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual([l[1] for l in linhas[1:]], ["João Teste"])

    def test_texto_que_parece_formula_e_neutralizado(self):
        self.a2.cliente.nome = "=SOMA(A1)"
        self.a2.cliente.save()
        texto = self._baixar().content.decode("utf-8-sig")
        self.assertIn("'=SOMA(A1)", texto)

    def test_periodo_sem_dados_gera_so_o_cabecalho(self):
        resp = self.client.get(reverse("dashboard_exportar"), {"periodo": "personalizado", "de": "2020-01-01", "ate": "2020-01-31"})
        self.assertEqual(len(resp.content.decode("utf-8-sig").strip().splitlines()), 1)
