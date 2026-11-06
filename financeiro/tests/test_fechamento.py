from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from financeiro import regras
from financeiro.forms import DespesaForm
from financeiro.models import Despesa, FechamentoMes, RegistroAuditoria

from .base import BaseFinanceiroTest, d
from .test_despesas import dados_despesa


class FechamentoDeMesTest(BaseFinanceiroTest):
    def setUp(self):
        super().setUp()
        regras.fechar_mes(d(1), self.admin)  # fecha março/2025

    def test_fechar_registra_quem_e_quando(self):
        f = FechamentoMes.objects.get(mes=d(1))
        self.assertTrue(f.fechado)
        self.assertEqual(f.fechado_por, self.admin)
        self.assertIsNotNone(f.fechado_em)
        self.assertTrue(RegistroAuditoria.objects.filter(entidade="mes", acao="fechado").exists())

    def test_nao_cria_recebimento_com_data_no_mes_fechado(self):
        with self.assertRaises(ValidationError) as ctx:
            self.receber(self.a3, "10", data=d(20))
        self.assertIn("03/2025 está fechado", ctx.exception.messages[0])
        self.assertEqual(self.a3.recebimentos.count(), 0)

    def test_nao_estorna_nem_edita_recebimento_do_mes_fechado(self):
        with self.assertRaises(ValidationError):
            regras.estornar_recebimento(self.r2b, "Motivo", self.admin)
        with self.assertRaises(ValidationError):
            regras.editar_recebimento(self.r2b, Decimal("50"), d(15), "pix", "", self.admin)
        r_abril = self.receber(self.a3, "10", data=d(1, 4))  # mês aberto
        with self.assertRaises(ValidationError):  # mudar a data PARA um mês fechado também é barrado
            regras.editar_recebimento(r_abril, Decimal("10"), d(20), "pix", "", self.admin)
        self.recarregar(self.r2b)
        self.assertFalse(self.r2b.estornado)

    def test_recebimento_em_mes_aberto_continua_funcionando(self):
        self.receber(self.a3, "10", data=d(2, 4))
        self.assertEqual(self.a3.recebimentos.count(), 1)

    def test_despesa_do_mes_fechado_nao_pode_ser_criada_editada_nem_excluida(self):
        form = DespesaForm(dados_despesa(self.cat["Outros"], vencimento="2025-03-18"), usuario=self.admin)
        self.assertFalse(form.is_valid())
        self.assertIn("fechado", " ".join(form.non_field_errors()))

        self.client.force_login(self.admin)
        resp = self.client.post(reverse("despesa_editar", args=[self.d3.pk]), dados_despesa(
            self.cat["Água/Luz/Internet"], descricao=self.d3.descricao, vencimento="2025-04-05", valor="999"))
        self.assertEqual(resp.status_code, 200)  # d3 vence em março (fechado): editar é barrado mesmo mudando para abril
        self.recarregar(self.d3)
        self.assertEqual(self.d3.valor, Decimal("200.00"))

        with self.assertRaises(ValidationError):
            regras.excluir_despesa(self.d1, self.admin)
        self.assertTrue(Despesa.objects.filter(pk=self.d1.pk).exists())

    def test_pagar_despesa_vencida_no_mes_fechado_vale_pela_data_do_pagamento(self):
        regras.pagar_despesa(self.d3, timezone.localdate(), "pix", self.admin)  # hoje: mês aberto
        self.recarregar(self.d3)
        self.assertIsNotNone(self.d3.data_pagamento)
        with self.assertRaises(ValidationError):
            regras.pagar_despesa(self.d5, d(20), "pix", self.admin)  # pagamento datado em março

    def test_reabrir_libera_e_registra_usuario_e_data(self):
        regras.reabrir_mes(d(1), self.admin)
        f = FechamentoMes.objects.get(mes=d(1))
        self.assertFalse(f.fechado)
        self.assertEqual(f.reaberto_por, self.admin)
        self.assertIsNotNone(f.reaberto_em)
        self.assertTrue(RegistroAuditoria.objects.filter(entidade="mes", acao="reaberto", usuario=self.admin).exists())
        self.receber(self.a3, "10", data=d(20))  # volta a funcionar
        with self.assertRaises(ValidationError):
            regras.reabrir_mes(d(1), self.admin)  # já está aberto

    def test_so_fecha_mes_que_ja_terminou(self):
        with self.assertRaises(ValidationError):
            regras.fechar_mes(timezone.localdate().replace(day=1), self.admin)
        with self.assertRaises(ValidationError):
            regras.fechar_mes(d(1), self.admin)  # já fechado

    def test_tela_mostra_meses_fechados(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("meses"))
        self.assertContains(resp, "03/2025")
        self.assertContains(resp, "Fechado por adm")
        self.assertContains(self.client.get(reverse("financeiro")), "03/2025")

    def test_fechar_e_reabrir_pela_tela(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("mes_fechar"), {"mes": "2025-02"})
        self.assertTrue(FechamentoMes.objects.get(mes=d(1, 2)).fechado)
        self.client.post(reverse("mes_reabrir"), {"mes": "2025-02"})
        self.assertFalse(FechamentoMes.objects.get(mes=d(1, 2)).fechado)
        resp = self.client.post(reverse("mes_fechar"), {"mes": "lixo"}, follow=True)
        self.assertContains(resp, "Mês inválido")
