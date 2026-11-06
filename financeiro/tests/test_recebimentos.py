from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import HistoricoAtendimento
from financeiro import regras
from financeiro.dinheiro import centavos, percentual, reais
from financeiro.models import Recebimento, RegistroAuditoria

from .base import BaseFinanceiroTest, d


class SituacaoCalculadaTest(BaseFinanceiroTest):
    def test_situacao_vem_da_soma_dos_recebimentos(self):
        self.recarregar(self.a1, self.a2, self.a3)
        self.assertEqual((self.a1.situacao_pagamento, self.a1.valor_pago), ("pago", Decimal("200.00")))
        self.assertEqual((self.a2.situacao_pagamento, self.a2.valor_pago), ("parcial", Decimal("200.00")))
        self.assertEqual((self.a3.situacao_pagamento, self.a3.valor_pago), ("pendente", Decimal("0.00")))

    def test_parcelado_em_partes_ate_quitar(self):
        self.receber(self.a3, "40")
        self.receber(self.a3, "60")
        self.recarregar(self.a3)
        self.assertEqual(self.a3.situacao_pagamento, "pago")
        self.assertEqual(self.a3.recebimentos.count(), 2)

    def test_estorno_recalcula_a_situacao(self):
        r40 = self.receber(self.a3, "40")
        r60 = self.receber(self.a3, "60")
        regras.estornar_recebimento(r60, "Cliente devolveu", self.admin)
        self.recarregar(self.a3)
        self.assertEqual((self.a3.situacao_pagamento, self.a3.valor_pago), ("parcial", Decimal("40.00")))
        regras.estornar_recebimento(r40, "Erro de digitação", self.admin)
        self.recarregar(self.a3)
        self.assertEqual((self.a3.situacao_pagamento, self.a3.valor_pago), ("pendente", Decimal("0.00")))

    def test_mudar_desconto_recalcula_a_situacao(self):
        # a2: 250, recebido 200 (parcial). Desconto de 50 -> valor devido 200 -> passa a pago.
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("atendimento_editar", args=[self.a2.pk]),
                                self.dados_form(valor_cobrado="250.00", desconto="50", status="concluido"))
        self.assertEqual(resp.status_code, 302)
        self.recarregar(self.a2)
        self.assertEqual(self.a2.situacao_pagamento, "pago")

    def test_nao_deixa_reduzir_o_valor_abaixo_do_recebido(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("atendimento_editar", args=[self.a2.pk]),
                                self.dados_form(valor_cobrado="250.00", desconto="100", status="concluido"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Já foram recebidos R$ 200,00")
        self.recarregar(self.a2)
        self.assertEqual(self.a2.desconto, Decimal("0.00"))


class LimitesDoRecebimentoTest(BaseFinanceiroTest):
    def test_total_recebido_nao_ultrapassa_o_valor_devido(self):
        self.receber(self.a3, "60")  # saldo 40
        with self.assertRaises(ValidationError) as ctx:
            self.receber(self.a3, "40.01")
        self.assertIn("maior que o saldo a receber", ctx.exception.messages[0])
        self.assertIn("R$ 40,00", ctx.exception.messages[0])
        self.assertEqual(self.a3.recebimentos.count(), 1)

    def test_atendimento_pago_nao_aceita_mais_recebimento(self):
        with self.assertRaises(ValidationError):
            self.receber(self.a1, "0.01")

    def test_valor_zero_ou_negativo_e_recusado(self):
        for valor in ("0", "-5"):
            with self.assertRaises(ValidationError) as ctx:
                regras.registrar_recebimento(self.a3, Decimal(valor), timezone.localdate(), "pix", "", self.admin)
            self.assertIn("maior que zero", ctx.exception.messages[0])

    def test_data_futura_e_recusada(self):
        amanha = timezone.localdate() + timedelta(days=1)
        with self.assertRaises(ValidationError) as ctx:
            regras.registrar_recebimento(self.a3, Decimal("10"), amanha, "pix", "", self.admin)
        self.assertIn("futuro", ctx.exception.messages[0])

    def test_atendimento_cancelado_nao_recebe(self):
        cancelado = self.criar(status="cancelado")
        with self.assertRaises(ValidationError):
            self.receber(cancelado, "10")

    def test_valor_e_arredondado_em_centavos(self):
        r = regras.registrar_recebimento(self.a3, Decimal("10.005"), timezone.localdate(), "pix", "", self.admin)
        self.assertEqual(r.valor, Decimal("10.01"))
        self.assertEqual(centavos(Decimal("2.004")), Decimal("2.00"))
        self.assertEqual(centavos(Decimal("2.675")), Decimal("2.68"))  # meio para cima, sem erro de float

    def test_formato_em_reais(self):
        self.assertEqual(reais(Decimal("1234.5")), "R$ 1.234,50")
        self.assertEqual(reais(Decimal("0")), "R$ 0,00")
        self.assertEqual(reais(Decimal("-5")), "-R$ 5,00")
        self.assertEqual(reais(None), "—")
        self.assertEqual(percentual(12.5), "12,5%")

    def test_formulario_valida_mensagens_em_portugues(self):
        self.client.force_login(self.admin)
        url = reverse("recebimento_novo")
        for valor, trecho in (("0", "maior que zero"), ("-3", "maior que zero"), ("abc", "valor válido"),
                              ("10.123", "casas decimais")):
            resp = self.client.post(url, {"atendimento": self.a3.pk, "valor": valor, "forma": "pix"})
            self.assertContains(resp, trecho)
        resp = self.client.post(url, {"atendimento": self.a3.pk, "valor": "10", "forma": ""})
        self.assertContains(resp, "Escolha a forma de pagamento")


class EstornoTest(BaseFinanceiroTest):
    def test_estorno_fica_registrado_e_nunca_apaga(self):
        regras.estornar_recebimento(self.r2b, "Cartão recusado", self.admin)
        self.recarregar(self.r2b)
        self.assertTrue(self.r2b.estornado)
        self.assertEqual((self.r2b.estornado_por, self.r2b.motivo_estorno), (self.admin, "Cartão recusado"))
        self.assertTrue(Recebimento.objects.filter(pk=self.r2b.pk).exists())
        self.assertEqual(self.r2b.atendimento.recebimentos.validos().count(), 1)
        auditoria = RegistroAuditoria.objects.get(entidade="recebimento", objeto_id=self.r2b.pk, acao="estornado")
        self.assertIn("Cartão recusado", auditoria.descricao)
        self.assertEqual(auditoria.usuario, self.admin)

    def test_estorno_entra_no_historico_do_atendimento(self):
        regras.estornar_recebimento(self.r2b, "Cartão recusado", self.admin)
        h = self.a2.historico.filter(tipo=HistoricoAtendimento.Tipo.PAGAMENTO).latest("id")
        self.assertEqual(h.valor_anterior, "Parcial (R$ 200,00)")
        self.assertIn("estorno de R$ 100,00", h.valor_novo)

    def test_estorno_exige_motivo_e_nao_se_repete(self):
        with self.assertRaises(ValidationError):
            regras.estornar_recebimento(self.r2b, "  ", self.admin)
        regras.estornar_recebimento(self.r2b, "Motivo", self.admin)
        with self.assertRaises(ValidationError) as ctx:
            regras.estornar_recebimento(self.r2b, "Motivo", self.admin)
        self.assertIn("já foi estornado", ctx.exception.messages[0])

    def test_estornado_nao_conta_no_saldo_nem_pode_ser_editado(self):
        regras.estornar_recebimento(self.r2b, "Motivo", self.admin)
        with self.assertRaises(ValidationError):
            regras.editar_recebimento(self.r2b, Decimal("10"), d(15), "pix", "", self.admin)
        self.receber(self.a2, "50")  # o saldo voltou a ser 100 - 50 = 50
        self.recarregar(self.a2)
        self.assertEqual(self.a2.valor_pago, Decimal("150.00"))

    def test_administrador_estorna_pela_tela(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("recebimento_estornar", args=[self.r2b.pk]), {"motivo": "Teste"})
        self.assertRedirects(resp, reverse("recebimento_detalhe", args=[self.r2b.pk]))
        self.recarregar(self.r2b)
        self.assertTrue(self.r2b.estornado)
        resp = self.client.post(reverse("recebimento_estornar", args=[self.r2a.pk]), {"motivo": ""})
        self.assertContains(resp, "Informe o motivo do estorno")


class EdicaoTest(BaseFinanceiroTest):
    def test_mudanca_de_valor_vai_para_auditoria_e_historico(self):
        regras.editar_recebimento(self.r2b, Decimal("50"), d(15), "pix", "ajuste", self.admin)
        self.recarregar(self.r2b, self.a2)
        self.assertEqual(self.r2b.valor, Decimal("50.00"))
        self.assertEqual(self.a2.valor_pago, Decimal("150.00"))
        auditoria = RegistroAuditoria.objects.get(entidade="recebimento", objeto_id=self.r2b.pk, acao="alterado")
        self.assertIn("valor: R$ 100,00 → R$ 50,00", auditoria.descricao)
        self.assertEqual(self.r2b.alterado_por, self.admin)
        self.assertTrue(self.a2.historico.filter(valor_novo__contains="ajustado de R$ 100,00 para R$ 50,00").exists())

    def test_edicao_nao_pode_ultrapassar_o_valor_devido(self):
        with self.assertRaises(ValidationError):
            regras.editar_recebimento(self.r2b, Decimal("151"), d(15), "pix", "", self.admin)

    def test_criacao_guarda_quem_criou(self):
        self.assertEqual(self.r1.criado_por, self.admin)
        self.assertTrue(RegistroAuditoria.objects.filter(entidade="recebimento", objeto_id=self.r1.pk, acao="criado").exists())
