from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from dashboard import graficos, periodos, services
from dashboard.periodos import Periodo

from .base import MARCO, BaseDashboardTest, filtros


class IndicadoresOperacionaisTest(BaseDashboardTest):
    def test_servicos_realizados_total_e_por_categoria(self):
        ind = services.indicadores_operacionais(filtros())
        self.assertEqual(ind["servicos"], 4)  # cancelado e em andamento não contam
        self.assertEqual(ind["por_categoria"], {
            "vistoria_cautelar": 2, "regravacao": 0, "capacitacao": 1, "limpeza": 1, "pequenos_reparos": 0})

    def test_alunos_atendidos_conta_alunos_diferentes(self):
        self.criar(status="concluido", data_atendimento=date(2025, 3, 20), tipo_servico=self.curso, veiculo=None,
                   aluno=self.aluno)  # mesmo aluno de novo
        ind = services.indicadores_operacionais(filtros())
        self.assertEqual(ind["por_categoria"]["capacitacao"], 2)
        self.assertEqual(ind["alunos_atendidos"], 1)

    def test_taxas(self):
        ind = services.indicadores_operacionais(filtros())
        # concluídos 4 / (4 concluídos + 1 cancelado + 1 em aberto vencido)
        self.assertEqual(ind["taxa_conclusao"], 66.7)
        self.assertEqual(ind["taxa_cancelamento"], 16.7)  # 1 de 6 atendimentos

    def test_taxa_de_nao_comparecimento(self):
        self.agendar(self.a1, self.hora_local(2025, 3, 5), "concluido")
        self.agendar(self.a2, self.hora_local(2025, 3, 10), "nao_compareceu")
        self.agendar(self.a5, self.hora_local(2025, 3, 20), "cancelado")  # liberou o horário: não conta
        self.agendar(self.a3, self.hora_local(2025, 3, 12), "remarcado")  # idem
        self.agendar(self.a6, self.hora_local(2025, 3, 25), "agendado")   # já passou, sem baixa: conta
        self.assertEqual(services.taxas(filtros())["nao_comparecimento"], 33.3)  # 1 de 3

    def test_agendamento_futuro_ainda_nao_entra_na_taxa_de_nao_comparecimento(self):
        amanha = timezone.now() + timedelta(days=1)
        self.agendar(self.criar(), amanha, "agendado")
        hoje = timezone.localdate()
        f = filtros(Periodo(periodos.PERSONALIZADO, hoje, hoje + timedelta(days=2)))
        self.assertIsNone(services.taxas(f)["nao_comparecimento"])

    def test_clientes_novos_e_recorrentes(self):
        ind = services.indicadores_operacionais(filtros())
        # João começou em março (novo); Maria já tinha atendimento em fevereiro (recorrente)
        self.assertEqual((ind["clientes_novos"], ind["clientes_recorrentes"]), (1, 1))

    def test_cliente_so_com_atendimento_cancelado_nao_conta(self):
        self.criar(status="cancelado", data_atendimento=date(2025, 3, 7), cliente=self.outro_cliente,
                   veiculo=self.veiculo_outro)
        ind = services.indicadores_operacionais(filtros())
        self.assertEqual(ind["clientes_novos"] + ind["clientes_recorrentes"], 2)

    def test_situacao_atual_em_aberto_e_agenda(self):
        self.criar(status="solicitado")
        self.agendar(self.a6, self.hora_local(2025, 3, 25), "agendado")                    # atrasado
        self.agendar(self.criar(status="agendado"), timezone.now() + timedelta(days=1), "confirmado")  # pendente
        self.agendar(self.criar(status="concluido"), timezone.now() - timedelta(days=1), "concluido")  # não é pendência
        s = services.situacao_atual(filtros())
        self.assertEqual(s["em_aberto"], 3)  # a6 (em andamento) + o solicitado + o agendado
        self.assertEqual((s["agendamentos_pendentes"], s["agendamentos_atrasados"]), (1, 1))

    def test_distribuicao_por_status(self):
        d = services.distribuicao_status(filtros())
        self.assertEqual(d, {"solicitado": 0, "agendado": 0, "em_andamento": 1, "concluido": 4, "cancelado": 1})

    def test_ranking_de_servicos_ordenado_por_quantidade(self):
        ranking = services.ranking_servicos(filtros())
        self.assertEqual([(r["nome"], r["n"]) for r in ranking], [("Vistoria", 2), ("Curso", 1), ("Limpeza", 1)])
        self.assertNotIn("faturamento", ranking[0])  # sem valores no perfil operacional

    def test_servicos_por_responsavel(self):
        self.agendar(self.a1, self.hora_local(2025, 3, 5), "concluido", responsavel=self.admin)
        self.agendar(self.a2, self.hora_local(2025, 3, 10), "concluido", responsavel=self.admin)
        self.agendar(self.a3, self.hora_local(2025, 3, 12), "concluido", responsavel=self.func)
        self.agendar(self.a6, self.hora_local(2025, 3, 25), "em_andamento", responsavel=self.func)  # não concluído
        r = services.servicos_por_responsavel(filtros())
        self.assertEqual([(x["responsavel"], x["n"]) for x in r], [("adm", 2), ("func", 1)])

    def test_abertos_mais_antigos(self):
        itens = services.abertos_mais_antigos(filtros())
        self.assertEqual([i["atendimento"] for i in itens], [self.a6])
        self.assertGreater(itens[0]["dias"], 300)

    def test_filtro_por_categoria(self):
        ind = services.indicadores_operacionais(filtros(categoria="limpeza"))
        self.assertEqual(ind["servicos"], 1)

    def test_filtro_por_responsavel_usa_os_agendamentos(self):
        self.agendar(self.a1, self.hora_local(2025, 3, 5), "concluido", responsavel=self.admin)
        self.agendar(self.a1, self.hora_local(2025, 3, 6), "concluido", responsavel=self.admin)  # 2 agendamentos, 1 atendimento
        f = filtros(responsavel_id=self.admin.pk)
        self.assertEqual(services.indicadores_operacionais(f)["servicos"], 1)
        self.assertEqual(services.faturamento(f)["faturamento"], Decimal("200.00"))  # sem somar duas vezes

    def test_painel_operacional_traz_comparativo_e_nao_traz_valores(self):
        painel = services.painel_operacional(filtros())
        # período anterior (29/01 a 28/02) teve 1 serviço: 4 contra 1 = +300%
        self.assertEqual(painel["comparativo"]["servicos"], {"texto": "+300%", "sentido": "positivo"})
        self.assertNotIn("faturamento", str(painel).lower())
        self.assertNotIn("ticket", str(painel).lower())


class IndicadoresFinanceirosTest(BaseDashboardTest):
    def test_faturamento_aplica_desconto_e_ignora_cancelados(self):
        # 200 (250-50) + 250 + 100 + 900; o cancelado (250) e o em andamento (100) ficam de fora
        r = services.faturamento(filtros())
        self.assertEqual(r["faturamento"], Decimal("1450.00"))
        self.assertEqual(r["ticket_medio"], Decimal("362.50"))

    def test_cancelado_nunca_entra_mesmo_se_estiver_pago(self):
        self.a5.status = "em_andamento"
        self.a5.save()
        self.receber(self.a5, data=date(2025, 3, 20))
        self.a5.status = "cancelado"
        self.a5.save()
        self.assertEqual(services.faturamento(filtros())["faturamento"], Decimal("1450.00"))

    def test_periodo_anterior_e_comparativo_financeiro(self):
        painel = services.painel_financeiro(filtros())
        self.assertEqual(painel["faturamento"], Decimal("1450.00"))
        # anterior: só B1 = 250  ->  (1450-250)/250 = +480%
        self.assertEqual(painel["comparativo"]["faturamento"]["texto"], "+480%")

    def test_a_receber_considera_nao_cancelados_do_periodo(self):
        # totais: 200+250+100+900+100 = 1550; pago: 200 (A1)  -> a receber 1350
        self.assertEqual(services.a_receber(filtros()), Decimal("1350.00"))

    def test_faturamento_por_categoria(self):
        v = services.faturamento_por_categoria(filtros())
        self.assertEqual(v["vistoria_cautelar"], Decimal("450.00"))
        self.assertEqual(v["limpeza"], Decimal("100.00"))
        self.assertEqual(v["capacitacao"], Decimal("900.00"))
        self.assertEqual(v["regravacao"], Decimal("0.00"))

    def test_ranking_com_valores_e_top_clientes(self):
        ranking = services.ranking_servicos(filtros(), com_valores=True)
        self.assertEqual([(r["nome"], r["faturamento"]) for r in ranking],
                         [("Vistoria", Decimal("450.00")), ("Curso", Decimal("900.00")), ("Limpeza", Decimal("100.00"))])
        top = services.top_clientes(filtros())
        self.assertEqual([(c["nome"], c["faturamento"], c["n"]) for c in top],
                         [("Maria Teste", Decimal("1350.00"), 3), ("João Teste", Decimal("100.00"), 1)])

    def test_situacao_dos_pagamentos_ignora_cancelados(self):
        self.assertEqual(services.situacao_pagamentos(filtros()), {"pendente": 4, "parcial": 0, "pago": 1})

    def test_top_clientes_limita_a_dez(self):
        for i in range(12):
            cliente = self.cliente.__class__.objects.create(nome=f"Cliente {i:02d}", telefone="1")
            self.criar(status="concluido", data_atendimento=date(2025, 3, 3), cliente=cliente,
                       tipo_servico=self.curso, veiculo=None, aluno=self.aluno)
        self.assertEqual(len(services.top_clientes(filtros())), 10)


class PeriodoSemDadosTest(BaseDashboardTest):
    def test_periodo_vazio_nao_quebra_e_mostra_zeros(self):
        vazio = filtros(Periodo(periodos.PERSONALIZADO, date(2020, 1, 1), date(2020, 1, 31)))
        painel = services.painel_operacional(vazio)
        ind = painel["indicadores"]
        self.assertEqual((ind["servicos"], ind["alunos_atendidos"], ind["clientes_novos"]), (0, 0, 0))
        self.assertTrue(all(v == 0 for v in ind["por_categoria"].values()))
        self.assertEqual((ind["taxa_conclusao"], ind["taxa_cancelamento"], ind["taxa_nao_comparecimento"]),
                         (None, None, None))
        self.assertEqual(painel["ranking"], [])
        fin = services.painel_financeiro(vazio)
        self.assertEqual((fin["faturamento"], fin["ticket_medio"], fin["a_receber"]), (Decimal("0.00"), None, Decimal("0.00")))
        self.assertEqual(fin["top_clientes"], [])

    def test_graficos_do_periodo_vazio_sao_marcados_como_vazios(self):
        vazio = filtros(Periodo(periodos.PERSONALIZADO, date(2020, 1, 1), date(2020, 1, 31)))
        painel = services.painel_operacional(vazio)
        self.assertTrue(graficos.status(painel["status"])["vazio"])
        self.assertTrue(graficos.ranking(painel["ranking"])["vazio"])
        self.assertTrue(graficos.barras_simples(painel["agenda"]["dias"], "x")["vazio"])
        self.assertTrue(graficos.pagamentos(services.situacao_pagamentos(vazio))["vazio"])


class SeriesMensaisTest(BaseDashboardTest):
    def test_doze_meses_com_zeros_e_agrupamento_por_mes(self):
        hoje = timezone.localdate()
        primeiro = hoje.replace(day=1)
        ultimo_do_mes_anterior = primeiro - timedelta(days=1)
        self.criar(status="concluido", data_atendimento=primeiro, desconto=Decimal("10"))
        self.criar(status="concluido", data_atendimento=ultimo_do_mes_anterior)
        self.criar(status="concluido", data_atendimento=ultimo_do_mes_anterior)
        antigo = periodos.primeiro_dia_meses_atras(hoje, 12)  # 13 meses atrás: fora da janela
        self.criar(status="concluido", data_atendimento=antigo)
        # os atendimentos de março/2025 do cenário também estão fora (a menos que "hoje" seja março/2026)

        serie = services.movimentacao_mensal(filtros())
        self.assertEqual(len(serie["meses"]), 12)
        self.assertEqual(serie["meses"][-1], primeiro)
        self.assertEqual(serie["total"][-1], 1)
        self.assertEqual(serie["total"][-2], 2)
        self.assertEqual(serie["por_categoria"]["vistoria_cautelar"][-2], 2)
        self.assertEqual(serie["por_categoria"]["limpeza"][-1], 0)

        dinheiro = services.faturamento_mensal(filtros())
        self.assertEqual(dinheiro["total"][-1], Decimal("240.00"))
        self.assertEqual(dinheiro["total"][-2], Decimal("500.00"))

    def test_serie_mensal_vira_json_sem_decimal(self):
        cfg = graficos.mensal(services.faturamento_mensal(filtros()), "Faturamento", formato="moeda")
        self.assertEqual(len(cfg["labels"]), 12)
        self.assertTrue(all(isinstance(v, float) for v in cfg["series"][0]["dados"]))
        self.assertEqual(len(cfg["series_empilhadas"]), 5)


class AgendaPorDiaEHorarioTest(BaseDashboardTest):
    def test_dia_da_semana_e_hora_usam_o_fuso_de_sao_paulo(self):
        # Segunda 10/03/2025 às 23:30 em São Paulo = terça 02:30 em UTC: tem que contar na SEGUNDA.
        self.agendar(self.a1, self.hora_local(2025, 3, 10, 23, 30), "concluido")
        # Quarta 12/03/2025 às 08:30 em São Paulo = 11:30 UTC: tem que contar às 8h, não às 11h.
        self.agendar(self.a3, self.hora_local(2025, 3, 12, 8, 30), "concluido")
        self.agendar(self.a2, self.hora_local(2025, 3, 12, 8, 45), "confirmado")
        self.agendar(self.a5, self.hora_local(2025, 3, 12, 9, 0), "cancelado")  # cancelado não é movimento
        mov = services.movimento_da_agenda(filtros())
        dias = dict(mov["dias"])
        self.assertEqual((dias["Seg"], dias["Ter"], dias["Qua"]), (1, 0, 2))
        horas = dict(mov["horas"])
        self.assertEqual((horas["8h"], horas["9h"], horas["11h"]), (2, 0, 0))
        self.assertEqual([r for r, _ in mov["dias"]], ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"])

    def test_agendamento_no_limite_do_periodo_respeita_o_fuso(self):
        # 31/03 às 23:00 local ainda é março, embora em UTC já seja 01/04.
        self.agendar(self.a1, self.hora_local(2025, 3, 31, 23, 0), "concluido")
        self.agendar(self.a2, self.hora_local(2025, 4, 1, 0, 30), "concluido")
        total = sum(n for _, n in services.movimento_da_agenda(filtros())["dias"])
        self.assertEqual(total, 1)
