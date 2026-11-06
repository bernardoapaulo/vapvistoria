from decimal import Decimal

from financeiro import graficos, services
from servicos.models import TipoServico

from .base import HOJE_FICTICIO, MARCO, BaseFinanceiroTest, d

D = Decimal


class CaixaTest(BaseFinanceiroTest):
    def test_resultado_e_margem_do_periodo(self):
        # recebido 200 + 100 + 100 + 900 = 1300 | pago 1000 + 60 = 1060 | resultado 240 | margem 240/1300
        r = services.resultado_do_periodo(MARCO)
        self.assertEqual((r["recebido"], r["pago"], r["resultado"]), (D("1300.00"), D("1060.00"), D("240.00")))
        self.assertEqual(r["margem"], 18.5)

    def test_despesa_em_aberto_nao_entra_no_caixa(self):
        self.assertEqual(services.total_pago(MARCO), D("1060.00"))  # os 200 de luz (D3) ainda não saíram

    def test_recebimento_estornado_sai_do_caixa(self):
        from financeiro import regras
        regras.estornar_recebimento(self.r2b, "Teste", self.admin)
        self.assertEqual(services.total_recebido(MARCO), D("1200.00"))

    def test_comparativo_com_periodo_anterior_negativo(self):
        # anterior (29/01 a 28/02): recebido 250, pago 1000, resultado -750
        p = services.painel(MARCO, HOJE_FICTICIO)
        self.assertEqual(p["comparativo"]["recebido"]["texto"], "+420%")      # (1300-250)/250
        self.assertEqual(p["comparativo"]["resultado"]["texto"], "+132%")     # (240+750)/|-750|
        self.assertEqual(p["comparativo"]["resultado"]["sentido"], "positivo")
        self.assertEqual(p["comparativo"]["pago"]["texto"], "+6%")            # (1060-1000)/1000

    def test_periodo_sem_dados_nao_quebra(self):
        from dashboard import periodos
        vazio = periodos.Periodo(periodos.PERSONALIZADO, d(1, 1, 2020), d(31, 1, 2020))
        r = services.resultado_do_periodo(vazio)
        self.assertEqual((r["recebido"], r["pago"], r["resultado"], r["margem"]), (D("0.00"), D("0.00"), D("0.00"), None))
        self.assertTrue(graficos.formas_de_pagamento(services.recebimentos_por_forma(vazio))["vazio"])
        self.assertEqual(services.fluxo_de_caixa(vazio)["linhas"], [])
        self.assertEqual(services.margem_por_servico(vazio), [])

    def test_conciliacao_entre_faturamento_e_recebido(self):
        # faturamento (concluídos): 200 + 250 + 100 + 900 = 1450 | recebido 1300 | diferença 150 (saldo de A2 e A3)
        c = services.conciliacao(MARCO, services.total_recebido(MARCO))
        self.assertEqual((c["faturamento"], c["recebido"], c["diferenca"]), (D("1450.00"), D("1300.00"), D("150.00")))

    def test_recebido_por_forma_e_por_categoria_de_servico(self):
        formas = services.recebimentos_por_forma(MARCO)
        self.assertEqual((formas["pix"], formas["cartao_credito"], formas["transferencia"], formas["dinheiro"]),
                         (D("200.00"), D("200.00"), D("900.00"), D("0.00")))
        por_categoria = services.receita_por_categoria(MARCO)
        self.assertEqual(por_categoria["vistoria_cautelar"], D("400.00"))
        self.assertEqual(por_categoria["capacitacao"], D("900.00"))
        self.assertEqual(por_categoria["limpeza"], D("0.00"))

    def test_despesas_por_categoria(self):
        self.assertEqual(services.despesas_por_categoria(MARCO),
                         [("Aluguel", D("1000.00")), ("Material de limpeza", D("60.00"))])


class MargemPorServicoTest(BaseFinanceiroTest):
    def test_lucro_e_margem_por_tipo_de_servico(self):
        linhas = {l["nome"]: l for l in services.margem_por_servico(MARCO)}
        # limpeza: faturamento 100 (A3) - despesa direta 60 (D2) = 40  -> 40%
        self.assertEqual((linhas["Limpeza"]["receita"], linhas["Limpeza"]["despesas"], linhas["Limpeza"]["lucro"]),
                         (D("100.00"), D("60.00"), D("40.00")))
        self.assertEqual(linhas["Limpeza"]["margem"], 40.0)
        self.assertEqual((linhas["Vistoria"]["receita"], linhas["Vistoria"]["margem"]), (D("450.00"), 100.0))
        self.assertEqual(linhas["Curso"]["lucro"], D("900.00"))

    def test_despesas_gerais_ficam_a_parte_e_nao_sao_distribuidas(self):
        # gerais de março (vencimento): aluguel 1000 + luz 200
        self.assertEqual(services.despesas_gerais(MARCO), D("1200.00"))
        total_diretas = sum(l["despesas"] for l in services.margem_por_servico(MARCO))
        self.assertEqual(total_diretas, D("60.00"))

    def test_servico_so_com_despesa_direta_aparece_com_margem_vazia(self):
        reparo = TipoServico.objects.create(nome="Reparo", categoria=TipoServico.Categoria.REPAROS, valor_padrao="10")
        self.despesa("Peças e reparos", 80, d(8), d(8), tipo_servico=reparo)
        linha = next(l for l in services.margem_por_servico(MARCO) if l["nome"] == "Reparo")
        self.assertEqual((linha["receita"], linha["lucro"], linha["margem"]), (D("0.00"), D("-80.00"), None))


class ContasTest(BaseFinanceiroTest):
    def test_a_receber_por_faixas_de_atraso(self):
        base = services.a_receber_base()
        faixas = {f["chave"]: f for f in services.faixas_a_receber(base, HOJE_FICTICIO)}
        # hoje = 20/04/2025
        self.assertEqual((faixas["a_vencer"]["valor"], faixas["a_vencer"]["quantidade"]), (D("70.00"), 1))      # A6 (25/04)
        self.assertEqual((faixas["1_30"]["valor"], faixas["1_30"]["quantidade"]), (D("80.00"), 1))              # A5 (18/04)
        self.assertEqual((faixas["31_60"]["valor"], faixas["31_60"]["quantidade"]), (D("150.00"), 2))           # A2 50 + A3 100
        self.assertEqual((faixas["mais_60"]["valor"], faixas["mais_60"]["quantidade"]), (D("120.00"), 1))      # A7 (15/01)
        self.assertEqual(sum(f["valor"] for f in faixas.values()), D("420.00"))

    def test_filtros_do_a_receber(self):
        base = services.a_receber_base(cliente_id=self.outro_cliente.pk)
        self.assertEqual({a.pk for a in base}, {self.a3.pk, self.a5.pk, self.a6.pk, self.a7.pk})
        periodo = services.a_receber_base(de=d(1), ate=d(31))
        self.assertEqual({a.pk for a in periodo}, {self.a2.pk, self.a3.pk})
        so_faixa = services.filtrar_faixa_receber(services.a_receber_base(), "31_60", HOJE_FICTICIO)
        self.assertEqual({a.pk for a in so_faixa}, {self.a2.pk, self.a3.pk})

    def test_atendimento_cancelado_nao_e_a_receber(self):
        self.a3.status = "cancelado"
        self.a3.save()
        self.assertNotIn(self.a3.pk, {a.pk for a in services.a_receber_base()})

    def test_a_pagar_por_faixas_de_vencimento(self):
        faixas = {f["chave"]: f for f in services.faixas_a_pagar(services.a_pagar_base(), HOJE_FICTICIO)}
        self.assertEqual(faixas["vencidas"]["valor"], D("200.00"))   # D3 (25/03)
        self.assertEqual(faixas["hoje"]["valor"], D("150.00"))       # D5 (20/04)
        self.assertEqual(faixas["7_dias"]["valor"], D("90.00"))      # D6 (25/04)
        self.assertEqual(faixas["30_dias"]["valor"], D("300.00"))    # D7 (15/05)
        self.assertEqual(faixas["depois"]["valor"], D("500.00"))     # D8 (10/07)
        self.assertEqual(sum(f["valor"] for f in faixas.values()), D("1240.00"))

    def test_despesa_paga_sai_do_a_pagar(self):
        self.assertNotIn(self.d1, services.a_pagar_base())
        self.assertIn(self.d3, services.a_pagar_base())

    def test_projecao_de_30_dias(self):
        p = services.projecao_30_dias(HOJE_FICTICIO)
        linhas = p["linhas"]
        # vencido: receber 50+100+80+120 = 350, pagar 200  -> 150 | hoje a 7 dias: +70 -240 -> -20 | 8-15: -20 | 16-30: -300 -> -320
        self.assertEqual([(l["entradas"], l["saidas"], l["acumulado"]) for l in linhas], [
            (D("350.00"), D("200.00"), D("150.00")), (D("70.00"), D("240.00"), D("-20.00")),
            (D("0.00"), D("0.00"), D("-20.00")), (D("0.00"), D("300.00"), D("-320.00"))])
        self.assertEqual(p["saldo_previsto"], D("-320.00"))

    def test_painel_resume_a_receber_e_a_pagar(self):
        p = services.painel(MARCO, HOJE_FICTICIO)
        self.assertEqual(p["a_receber"], D("420.00"))
        self.assertEqual(p["a_receber_atrasado"], D("350.00"))
        self.assertEqual(p["a_pagar"], D("1240.00"))
        self.assertEqual(p["a_pagar_vencido"], D("200.00"))
        self.assertEqual(p["saldo_previsto"], D("-320.00"))


class FluxoDeCaixaTest(BaseFinanceiroTest):
    def test_fluxo_por_dia_com_saldo_acumulado(self):
        f = services.fluxo_de_caixa(MARCO, "dia")
        self.assertEqual([(l["data"], l["entradas"], l["saidas"], l["acumulado"]) for l in f["linhas"]], [
            (d(5), D("200.00"), D("1000.00"), D("-800.00")),
            (d(10), D("100.00"), D("0.00"), D("-700.00")),
            (d(11), D("0.00"), D("60.00"), D("-760.00")),
            (d(15), D("100.00"), D("0.00"), D("-660.00")),
            (d(20), D("900.00"), D("0.00"), D("240.00")),
        ])
        self.assertEqual((f["total_entradas"], f["total_saidas"], f["saldo"]), (D("1300.00"), D("1060.00"), D("240.00")))

    def test_fluxo_por_mes(self):
        f = services.fluxo_de_caixa(MARCO, "mes")
        self.assertEqual(len(f["linhas"]), 1)
        self.assertEqual((f["linhas"][0]["data"], f["linhas"][0]["saldo"]), (d(1), D("240.00")))

    def test_serie_de_12_meses_tem_zeros_e_resultado(self):
        serie = services.serie_mensal(12)
        self.assertEqual(len(serie["meses"]), 12)
        self.assertEqual(len(serie["resultado"]), 12)
        self.assertEqual(serie["resultado"][-1], serie["entradas"][-1] - serie["saidas"][-1])

    def test_graficos_chegam_com_numeros_comuns(self):
        g = graficos.entradas_e_saidas(services.serie_mensal(12))
        self.assertEqual(len(g["series"]), 2)
        self.assertTrue(all(isinstance(v, float) for s in g["series"] for v in s["dados"]))
        self.assertEqual(graficos.margem_por_servico(services.margem_por_servico(MARCO))["tipo"], "barh")


class RelatorioMensalTest(BaseFinanceiroTest):
    def test_relatorio_de_marco(self):
        r = services.relatorio_mensal(2025, 3)
        self.assertEqual((r["recebido"], r["pago"], r["resultado"], r["margem"]), (D("1300.00"), D("1060.00"), D("240.00"), 18.5))
        receitas = dict(r["receitas"])
        self.assertEqual(receitas["Vistoria cautelar"], D("400.00"))
        self.assertEqual(receitas["Capacitação"], D("900.00"))
        self.assertEqual((r["despesas_diretas"], r["despesas_gerais_pagas"]), (D("60.00"), D("1000.00")))
        self.assertEqual(r["periodo"].inicio, d(1))
        self.assertEqual(r["periodo"].fim, d(31))


class DesempenhoTest(BaseFinanceiroTest):
    def test_painel_usa_poucas_consultas(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            services.painel(MARCO, HOJE_FICTICIO)
        self.assertLess(len(ctx), 45)
