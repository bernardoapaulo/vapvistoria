from decimal import Decimal

from django.urls import reverse

from atendimentos.models import Atendimento

from .base import BaseAtendimentoTest


class PermissoesAtendimentoTest(BaseAtendimentoTest):
    def test_anonimo_vai_para_o_login(self):
        a = self.criar()
        for url in (reverse("atendimento_lista"), reverse("atendimento_novo"),
                    reverse("atendimento_detalhe", args=[a.pk]), reverse("atendimento_editar", args=[a.pk])):
            self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
        resp = self.client.post(reverse("atendimento_status", args=[a.pk, "agendado"]))
        self.assertEqual(resp.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.status, "solicitado")

    def test_funcionario_cria_com_valor_padrao_e_ignora_valor_enviado(self):
        self.client.force_login(self.func)
        resp = self.client.post(reverse("atendimento_novo"), self.dados_form(valor_cobrado="1", desconto="200"))
        self.assertEqual(resp.status_code, 302)
        a = Atendimento.objects.get()
        self.assertEqual((a.valor_cobrado, a.desconto), (Decimal("250.00"), Decimal("0.00")))

    def test_funcionario_nao_ve_campos_de_valor(self):
        self.client.force_login(self.func)
        resp = self.client.get(reverse("atendimento_novo"))
        self.assertNotContains(resp, 'name="valor_cobrado"')
        self.assertNotContains(resp, 'name="desconto"')
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("atendimento_novo"))
        self.assertContains(resp, 'name="valor_cobrado"')

    def test_funcionario_nao_altera_valor_nem_desconto_ao_editar(self):
        a = self.criar(registrado_por=self.func)
        self.client.force_login(self.func)
        self.client.post(reverse("atendimento_editar", args=[a.pk]),
                         self.dados_form(valor_cobrado="1", desconto="100", observacoes="ok"))
        a.refresh_from_db()
        self.assertEqual((a.valor_cobrado, a.desconto, a.observacoes), (Decimal("250.00"), Decimal("0.00"), "ok"))

    def test_trocar_servico_pelo_funcionario_atualiza_para_o_valor_padrao_novo(self):
        a = self.criar()
        self.client.force_login(self.func)
        self.client.post(reverse("atendimento_editar", args=[a.pk]),
                         self.dados_form(tipo_servico=self.limpeza.pk))
        a.refresh_from_db()
        self.assertEqual(a.valor_cobrado, Decimal("100.00"))

    def test_administrador_altera_valor_e_desconto(self):
        a = self.criar()
        self.client.force_login(self.admin)
        self.client.post(reverse("atendimento_editar", args=[a.pk]),
                         self.dados_form(valor_cobrado="300", desconto="30"))
        a.refresh_from_db()
        self.assertEqual((a.valor_cobrado, a.desconto), (Decimal("300.00"), Decimal("30.00")))

    def test_funcionario_nao_exclui(self):
        a = self.criar()
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("atendimento_excluir", args=[a.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("atendimento_excluir", args=[a.pk])).status_code, 403)
        self.assertTrue(Atendimento.objects.filter(pk=a.pk).exists())

    def test_administrador_exclui(self):
        a = self.criar()
        self.client.force_login(self.admin)
        self.client.post(reverse("atendimento_excluir", args=[a.pk]))
        self.assertFalse(Atendimento.objects.filter(pk=a.pk).exists())

    def test_funcionario_nao_reabre_nem_edita_fechado(self):
        a = self.criar(status="concluido")
        self.client.force_login(self.func)
        self.assertEqual(self.client.post(reverse("atendimento_status", args=[a.pk, "em_andamento"])).status_code, 403)
        self.assertEqual(self.client.get(reverse("atendimento_editar", args=[a.pk])).status_code, 403)
        a.refresh_from_db()
        self.assertEqual(a.status, "concluido")
        resp = self.client.get(reverse("atendimento_detalhe", args=[a.pk]))
        self.assertNotContains(resp, "Reabrir")

    def test_funcionario_ainda_registra_pagamento_de_atendimento_concluido(self):
        a = self.criar(status="concluido")
        self.client.force_login(self.func)
        self.client.post(reverse("atendimento_receber", args=[a.pk]), {"valor": "250.00", "forma": "pix"})
        a.refresh_from_db()
        self.assertEqual(a.situacao_pagamento, "pago")

    def test_administrador_ve_botao_reabrir(self):
        a = self.criar(status="cancelado")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("atendimento_detalhe", args=[a.pk])), "Reabrir")

    def test_botoes_rapidos_exigem_post(self):
        a = self.criar()
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("atendimento_status", args=[a.pk, "agendado"])).status_code, 405)

    def test_cliente_com_atendimento_nao_pode_ser_excluido(self):
        self.criar()
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("cliente_excluir", args=[self.cliente.pk]))
        self.assertContains(resp, "não pode ser excluído")
