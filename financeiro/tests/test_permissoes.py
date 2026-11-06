from django.urls import reverse

from financeiro.models import Despesa, Recebimento

from .base import BaseFinanceiroTest

PAGINAS_DO_MODULO = [
    "financeiro", "contas_receber", "contas_pagar", "fluxo_caixa", "recebimento_lista", "recebimento_novo",
    "despesa_lista", "despesa_novo", "categoria_despesa_lista", "categoria_despesa_novo", "relatorio_mensal",
    "relatorio_csv", "meses",
]


class FuncionarioNaoAcessaOFinanceiroTest(BaseFinanceiroTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.func)

    def test_nenhuma_pagina_do_modulo_abre(self):
        for nome in PAGINAS_DO_MODULO:
            self.assertEqual(self.client.get(reverse(nome)).status_code, 403, nome)
        pks = {
            "recebimento_detalhe": self.r1.pk, "recebimento_editar": self.r1.pk, "recebimento_estornar": self.r1.pk,
            "despesa_detalhe": self.d1.pk, "despesa_editar": self.d1.pk, "despesa_excluir": self.d1.pk,
            "despesa_comprovante": self.d1.pk,
        }
        for nome, pk in pks.items():
            self.assertEqual(self.client.get(reverse(nome, args=[pk])).status_code, 403, nome)

    def test_acoes_de_escrita_sao_barradas_no_servidor(self):
        self.assertEqual(self.client.post(reverse("recebimento_estornar", args=[self.r2b.pk]), {"motivo": "x"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("recebimento_editar", args=[self.r2b.pk]),
                                          {"valor": "1", "data": "2025-03-15", "forma": "pix"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("despesa_pagar", args=[self.d3.pk]), {"forma": "pix"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("despesa_excluir", args=[self.d3.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("mes_fechar"), {"mes": "2025-02"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("recebimento_novo"), {"atendimento": self.a3.pk, "valor": "5", "forma": "pix"}).status_code, 403)
        self.recarregar(self.r2b, self.d3)
        self.assertFalse(self.r2b.estornado)
        self.assertIsNone(self.d3.data_pagamento)
        self.assertEqual(Recebimento.objects.filter(atendimento=self.a3).count(), 0)

    def test_funcionario_nao_ve_o_financeiro_nem_no_menu_nem_na_inicio(self):
        resp = self.client.get(reverse("inicio"))
        self.assertNotContains(resp, reverse("financeiro"))
        self.assertNotContains(resp, "Financeiro do mês")
        self.assertNotIn("resumo_financeiro", resp.context)

    def test_funcionario_registra_recebimento_pela_tela_do_atendimento(self):
        resp = self.client.post(reverse("atendimento_receber", args=[self.a3.pk]),
                                {"valor": "30.00", "forma": "dinheiro", "observacao": "sinal"})
        self.assertRedirects(resp, self.a3.get_absolute_url())
        r = Recebimento.objects.get(atendimento=self.a3)
        self.assertEqual((r.valor, r.forma, r.criado_por), (30, "dinheiro", self.func))
        self.recarregar(self.a3)
        self.assertEqual(self.a3.situacao_pagamento, "parcial")

    def test_funcionario_nao_escolhe_a_data_do_recebimento(self):
        from django.utils import timezone
        self.client.post(reverse("atendimento_receber", args=[self.a3.pk]),
                         {"valor": "30.00", "forma": "pix", "data": "2020-01-01"})  # tentativa de retroagir
        self.assertEqual(Recebimento.objects.get(atendimento=self.a3).data, timezone.localdate())
        html = self.client.get(self.a3.get_absolute_url()).content.decode()
        self.assertNotIn('name="data"', html)

    def test_funcionario_recebimento_acima_do_devido_e_barrado(self):
        resp = self.client.post(reverse("atendimento_receber", args=[self.a3.pk]), {"valor": "500", "forma": "pix"}, follow=True)
        self.assertContains(resp, "maior que o saldo a receber")
        self.assertEqual(Recebimento.objects.filter(atendimento=self.a3).count(), 0)

    def test_tela_do_atendimento_nao_oferece_estorno_nem_links_financeiros(self):
        resp = self.client.get(self.a2.get_absolute_url())
        self.assertContains(resp, "Recebimentos")
        self.assertNotContains(resp, "Estornar")
        self.assertNotContains(resp, "/financeiro/")

    def test_funcionario_nao_altera_pagamento_editando_o_atendimento(self):
        resp = self.client.post(reverse("atendimento_editar", args=[self.a3.pk]), self.dados_form(
            cliente=self.outro_cliente.pk, veiculo=self.veiculo_outro.pk, tipo_servico=self.limpeza.pk,
            status="concluido", data_atendimento="2025-03-12", situacao_pagamento="pago", valor_pago="100"))
        self.recarregar(self.a3)
        self.assertEqual((self.a3.situacao_pagamento, self.a3.valor_pago), ("pendente", 0))

    def test_permissoes_dos_perfis(self):
        self.assertTrue(self.func.has_perm("financeiro.add_recebimento"))
        for perm in ("ver_financeiro", "view_recebimento", "change_recebimento", "estornar_recebimento", "view_despesa",
                     "add_despesa", "delete_despesa", "fechar_mes", "view_categoriadespesa"):
            self.assertFalse(self.func.has_perm(f"financeiro.{perm}"), perm)
            self.assertTrue(self.admin.has_perm(f"financeiro.{perm}"), perm)


class AdministradorEAnonimoTest(BaseFinanceiroTest):
    def test_anonimo_vai_para_o_login(self):
        for nome in PAGINAS_DO_MODULO:
            resp = self.client.get(reverse(nome))
            self.assertEqual(resp.status_code, 302, nome)
            self.assertIn("/entrar/", resp.url)
        resp = self.client.post(reverse("atendimento_receber", args=[self.a3.pk]), {"valor": "5", "forma": "pix"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Recebimento.objects.filter(atendimento=self.a3).count(), 0)

    def test_administrador_abre_todas_as_paginas(self):
        self.client.force_login(self.admin)
        for nome in PAGINAS_DO_MODULO:
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)
        for nome, pk in {"recebimento_detalhe": self.r1.pk, "recebimento_editar": self.r1.pk,
                         "recebimento_estornar": self.r1.pk, "despesa_detalhe": self.d1.pk,
                         "despesa_editar": self.d1.pk, "despesa_excluir": self.d1.pk}.items():
            self.assertEqual(self.client.get(reverse(nome, args=[pk])).status_code, 200, nome)

    def test_menu_e_inicio_do_administrador(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("inicio"))
        self.assertContains(resp, reverse("financeiro"))
        self.assertContains(resp, "Financeiro do mês")
        self.assertIn("recebido", resp.context["resumo_financeiro"])

    def test_dashboard_de_desempenho_explica_a_diferenca_so_para_o_administrador(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("dashboard")), "Faturamento ≠ dinheiro recebido")
        self.client.force_login(self.func)
        self.assertNotContains(self.client.get(reverse("dashboard")), "dinheiro recebido")

    def test_nada_foi_excluido_nas_tentativas_barradas(self):
        self.assertEqual(Despesa.objects.count(), 8)
