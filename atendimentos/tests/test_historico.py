from django.urls import reverse

from atendimentos.models import Atendimento, HistoricoAtendimento

from .base import BaseAtendimentoTest

Tipo = HistoricoAtendimento.Tipo


class HistoricoTest(BaseAtendimentoTest):
    def setUp(self):
        self.client.force_login(self.func)

    def _historico(self, a):
        return list(a.historico.values_list("tipo", "valor_anterior", "valor_novo", "usuario__username"))

    def test_criacao_gera_historico_com_usuario(self):
        self.client.post(reverse("atendimento_novo"), self.dados_form())
        a = Atendimento.objects.get()
        self.assertEqual(a.registrado_por, self.func)
        self.assertEqual(self._historico(a), [(Tipo.CRIACAO, "", "Atendimento criado (Solicitado)", "func")])

    def test_botoes_rapidos_geram_historico_de_status(self):
        a = self.criar(registrado_por=self.func)
        for novo in ("em_andamento", "concluido"):
            self.client.post(reverse("atendimento_status", args=[a.pk, novo]))
        a.refresh_from_db()
        self.assertEqual(a.status, "concluido")
        self.assertEqual(self._historico(a), [
            (Tipo.STATUS, "Solicitado", "Em andamento", "func"),
            (Tipo.STATUS, "Em andamento", "Concluído", "func"),
        ])

    def test_transicao_invalida_e_recusada(self):
        a = self.criar()
        self.client.post(reverse("atendimento_status", args=[a.pk, "concluido"]))  # pula etapas
        a.refresh_from_db()
        self.assertEqual(a.status, "solicitado")
        self.assertEqual(a.historico.count(), 0)

    def test_recebimento_gera_historico_de_pagamento(self):
        a = self.criar()
        self.client.post(reverse("atendimento_receber", args=[a.pk]), {"valor": "250.00", "forma": "pix"})
        a.refresh_from_db()
        self.assertEqual(a.situacao_pagamento, "pago")
        self.assertEqual(a.valor_pago, a.valor_final)
        ((tipo, antes, novo, quem),) = self._historico(a)
        self.assertEqual((tipo, antes, quem), (Tipo.PAGAMENTO, "Pendente", "func"))
        self.assertTrue(novo.startswith("Pago · recebimento de R$ 250,00 via Pix"))

    def test_recebimento_exige_forma(self):
        a = self.criar()
        self.client.post(reverse("atendimento_receber", args=[a.pk]), {"valor": "250.00"})
        a.refresh_from_db()
        self.assertEqual(a.situacao_pagamento, "pendente")

    def test_edicao_pelo_formulario_registra_status(self):
        a = self.criar(registrado_por=self.func)
        self.client.post(reverse("atendimento_editar", args=[a.pk]), self.dados_form(status="agendado"))
        self.assertEqual([t for t, *_ in self._historico(a)], [Tipo.STATUS])

    def test_edicao_sem_mudancas_nao_gera_historico(self):
        a = self.criar(registrado_por=self.func)
        self.client.post(reverse("atendimento_editar", args=[a.pk]), self.dados_form())
        self.assertEqual(a.historico.count(), 0)

    def test_reabertura_pelo_administrador_entra_no_historico(self):
        a = self.criar(status="concluido")
        self.client.force_login(self.admin)
        self.client.post(reverse("atendimento_status", args=[a.pk, "em_andamento"]))
        a.refresh_from_db()
        self.assertEqual(a.status, "em_andamento")
        self.assertEqual(self._historico(a), [(Tipo.REABERTURA, "Concluído", "Em andamento", "adm")])

    def test_mudanca_de_valor_pelo_admin_e_registrada(self):
        a = self.criar()
        self.client.force_login(self.admin)
        self.client.post(reverse("atendimento_editar", args=[a.pk]), self.dados_form(desconto="25"))
        self.assertEqual(a.historico.get().tipo, Tipo.VALOR)

    def test_detalhe_mostra_linha_do_tempo(self):
        a = self.criar()
        self.client.post(reverse("atendimento_status", args=[a.pk, "agendado"]))
        resp = self.client.get(reverse("atendimento_detalhe", args=[a.pk]))
        self.assertContains(resp, "linha-do-tempo")
        self.assertContains(resp, "Solicitado")
        self.assertContains(resp, "Agendado")
