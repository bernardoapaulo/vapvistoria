import csv
import io
from datetime import date

from django.urls import reverse

from .base import BaseFinanceiroTest

MARCO = {"periodo": "personalizado", "de": "2025-03-01", "ate": "2025-03-31"}


class TelasDoFinanceiroTest(BaseFinanceiroTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_finance_dashboard_mostra_os_numeros_do_periodo(self):
        resp = self.client.get(reverse("financeiro"), MARCO)
        self.assertContains(resp, "R$ 1.300,00")   # recebido
        self.assertContains(resp, "R$ 1.060,00")   # despesas pagas
        self.assertContains(resp, "R$ 240,00")     # resultado
        self.assertContains(resp, "18,5%")         # margem
        self.assertContains(resp, "+420%")         # comparativo do recebido
        self.assertContains(resp, "Faturamento × dinheiro recebido")
        self.assertContains(resp, "R$ 1.450,00")   # faturamento do dashboard de desempenho
        self.assertContains(resp, "Como os números são calculados")
        for grafico in ("g-despesas", "g-formas", "g-receita", "g-margem"):
            self.assertContains(resp, f'data-grafico="{grafico}"')
        self.assertContains(resp, "vendor/chartjs/chart.umd.min.js")

    def test_graficos_de_12_meses_aparecem_quando_ha_movimento_recente(self):
        # os dados de teste são de 2025; um recebimento de hoje entra na janela dos últimos 12 meses
        self.receber(self.a3, "10")
        resp = self.client.get(reverse("financeiro"), MARCO)
        self.assertContains(resp, 'data-grafico="g-entradas-saidas"')
        self.assertContains(resp, 'data-grafico="g-resultado"')

    def test_filtros_invalidos_e_periodo_vazio_nao_quebram(self):
        for params in ({"periodo": "xx"}, {"de": "lixo", "ate": "2025-01-01", "periodo": "personalizado"}, {}):
            self.assertEqual(self.client.get(reverse("financeiro"), params).status_code, 200)
        vazio = self.client.get(reverse("financeiro"), {"periodo": "personalizado", "de": "2020-01-01", "ate": "2020-01-31"})
        self.assertContains(vazio, "Sem dados neste período.")
        self.assertEqual(vazio.context["p"]["resultado"], 0)

    def test_contas_a_receber_lista_e_filtra(self):
        resp = self.client.get(reverse("contas_receber"))
        self.assertEqual({a.pk for a in resp.context["atendimentos"]}, {self.a2.pk, self.a3.pk, self.a5.pk, self.a6.pk, self.a7.pk})
        self.assertContains(resp, "Registrar recebimento")
        self.assertContains(resp, "R$ 420,00")
        filtrada = self.client.get(reverse("contas_receber"), {"cliente": self.cliente.pk})
        self.assertEqual({a.pk for a in filtrada.context["atendimentos"]}, {self.a2.pk})
        sem_efeito = self.client.get(reverse("contas_receber"), {"cliente": "abc", "faixa": "zzz", "de": "x"})
        self.assertEqual(sem_efeito.status_code, 200)

    def test_botao_rapido_registra_e_volta_para_a_lista(self):
        url = reverse("contas_receber") + "?cliente=" + str(self.outro_cliente.pk)
        resp = self.client.post(reverse("atendimento_receber", args=[self.a3.pk]),
                                {"valor": "100.00", "forma": "pix", "voltar": url})
        self.assertRedirects(resp, url)
        self.recarregar(self.a3)
        self.assertEqual(self.a3.situacao_pagamento, "pago")
        # destino de fora do módulo é ignorado (nada de redirecionamento aberto)
        resp = self.client.post(reverse("atendimento_receber", args=[self.a5.pk]),
                                {"valor": "10", "forma": "pix", "voltar": "https://exemplo.com/"})
        self.assertRedirects(resp, self.a5.get_absolute_url())

    def test_contas_a_pagar_lista_e_marca_como_paga(self):
        resp = self.client.get(reverse("contas_pagar"))
        self.assertEqual(resp.context["total"], 1240)
        self.assertContains(resp, "Marcar como paga")
        self.assertContains(resp, "Vencidas")
        self.client.post(reverse("despesa_pagar", args=[self.d3.pk]), {"forma": "pix", "voltar": reverse("contas_pagar")})
        self.recarregar(self.d3)
        self.assertTrue(self.d3.paga)
        # os dados de teste são de 2025, então hoje todas as em aberto já estão vencidas
        vencidas = self.client.get(reverse("contas_pagar"), {"faixa": "vencidas"})
        self.assertEqual({d.pk for d in vencidas.context["despesas"]}, {self.d5.pk, self.d6.pk, self.d7.pk, self.d8.pk})
        self.assertEqual(self.client.get(reverse("contas_pagar"), {"faixa": "depois"}).context["paginator"].count, 0)

    def test_fluxo_de_caixa(self):
        resp = self.client.get(reverse("fluxo_caixa"), MARCO)
        self.assertEqual(len(resp.context["fluxo"]["linhas"]), 5)
        self.assertContains(resp, "R$ 240,00")
        self.assertContains(resp, "Projeção dos próximos 30 dias")
        por_mes = self.client.get(reverse("fluxo_caixa"), {**MARCO, "agrupar": "mes"})
        self.assertEqual(len(por_mes.context["fluxo"]["linhas"]), 1)

    def test_lista_de_recebimentos_busca_filtra_e_pagina(self):
        url = reverse("recebimento_lista")
        self.assertEqual(self.client.get(url).context["paginator"].count, 5)  # r1, r2a, r2b, r4 e o de fevereiro
        self.assertEqual(self.client.get(url, {"forma": "transferencia"}).context["paginator"].count, 1)
        self.assertEqual(self.client.get(url, {"q": "Maria"}).context["paginator"].count, 5)
        self.assertEqual(self.client.get(url, {"q": "inexistente"}).context["paginator"].count, 0)
        self.assertEqual(self.client.get(url, {"de": "2025-03-10", "ate": "2025-03-15"}).context["paginator"].count, 2)
        self.assertEqual(self.client.get(url, {"situacao": "estornados"}).context["paginator"].count, 0)
        from financeiro import regras
        regras.estornar_recebimento(self.r2b, "Teste", self.admin)
        self.assertEqual(self.client.get(url, {"situacao": "estornados"}).context["paginator"].count, 1)
        self.assertEqual(self.client.get(url, {"situacao": "todos"}).context["paginator"].count, 5)

    def test_lista_de_despesas_busca_filtra_e_pagina(self):
        url = reverse("despesa_lista")
        self.assertEqual(self.client.get(url).context["paginator"].count, 8)
        self.assertEqual(self.client.get(url, {"situacao": "em_aberto"}).context["paginator"].count, 5)
        self.assertEqual(self.client.get(url, {"situacao": "pagas"}).context["paginator"].count, 3)
        vencidas = self.client.get(url, {"situacao": "vencidas"}).context["object_list"]
        self.assertEqual({d.pk for d in vencidas}, {self.d3.pk, self.d5.pk, self.d6.pk, self.d7.pk, self.d8.pk})  # todas já passaram
        self.assertEqual(self.client.get(url, {"categoria": self.cat["Aluguel"].pk}).context["paginator"].count, 2)
        self.assertEqual(self.client.get(url, {"q": "Material"}).context["paginator"].count, 1)
        self.assertEqual(self.client.get(url, {"de": "2025-03-01", "ate": "2025-03-31"}).context["paginator"].count, 3)

    def test_detalhes_mostram_auditoria(self):
        self.assertContains(self.client.get(self.r1.get_absolute_url()), "Auditoria")
        self.assertContains(self.client.get(self.d1.get_absolute_url()), "Auditoria")

    def test_criar_recebimento_pela_area_financeira(self):
        resp = self.client.post(reverse("recebimento_novo"), {
            "atendimento": self.a3.pk, "valor": "60.00", "forma": "pix", "data": "2025-04-02", "observacao": "teste"})
        recebimento = self.a3.recebimentos.get()
        self.assertRedirects(resp, recebimento.get_absolute_url())
        self.assertEqual((recebimento.valor, recebimento.data), (60, date(2025, 4, 2)))
        # só aparecem atendimentos com saldo na escolha
        form = self.client.get(reverse("recebimento_novo")).context["form"]
        self.assertNotIn(self.a1, form.fields["atendimento"].queryset)

    def test_editar_recebimento_pela_tela(self):
        self.client.post(reverse("recebimento_editar", args=[self.r2b.pk]),
                         {"valor": "80.00", "data": "2025-03-16", "forma": "dinheiro", "observacao": "ajuste"})
        self.recarregar(self.r2b)
        self.assertEqual((self.r2b.valor, self.r2b.data, self.r2b.forma), (80, date(2025, 3, 16), "dinheiro"))

    def test_relatorio_mensal_na_tela_e_pronto_para_imprimir(self):
        resp = self.client.get(reverse("relatorio_mensal"), {"mes": "2025-03"})
        self.assertContains(resp, "R$ 1.300,00")
        self.assertContains(resp, "R$ 240,00")
        self.assertContains(resp, "Receitas por categoria de serviço")
        self.assertContains(resp, "Despesas pagas por categoria")
        self.assertContains(resp, "window.print()")
        self.assertContains(self.client.get(reverse("relatorio_mensal"), {"mes": "lixo"}), "Resultado do mês")

    def test_relatorio_em_css_de_impressao(self):
        from django.conf import settings
        css = (settings.BASE_DIR / "static" / "css" / "impressao.css").read_text(encoding="utf-8")
        self.assertIn("@media print", css)

    def test_relatorio_csv_para_excel_em_portugues(self):
        resp = self.client.get(reverse("relatorio_csv"), {"mes": "2025-03"})
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("resultado_2025-03.csv", resp["Content-Disposition"])
        self.assertTrue(resp.content.startswith("﻿".encode("utf-8")))
        linhas = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        achado = {l[0]: l[1:] for l in linhas if l}
        self.assertEqual(achado["Total recebido"], ["1300,00"])
        self.assertEqual(achado["Total de despesas pagas"], ["1060,00"])
        self.assertEqual(achado["Resultado (recebido - despesas pagas)"], ["240,00"])
        self.assertEqual(achado["Margem (%)"], ["18,5"])
        self.assertEqual(achado["Capacitação"], ["900,00"])

    def test_csv_do_dashboard_continua_com_forma_de_pagamento(self):
        resp = self.client.get(reverse("dashboard_exportar"), MARCO)
        texto = resp.content.decode("utf-8-sig")
        self.assertIn("Cartão de crédito", texto)  # a2: dois recebimentos no crédito
        self.assertIn("Transferência", texto)

    def test_atendimento_mostra_recebimentos_e_estorno_para_o_administrador(self):
        resp = self.client.get(self.a2.get_absolute_url())
        self.assertContains(resp, "Estornar")
        self.assertContains(resp, "R$ 100,00")
        self.assertContains(resp, "Registrar recebimento")
