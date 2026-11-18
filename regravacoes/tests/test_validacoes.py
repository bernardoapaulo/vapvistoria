from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from regravacoes.models import RegistroRegravacao, validar_ano_modelo

from .base import BaseRegravacaoTest

S = RegistroRegravacao.Status


class ValidacaoDosDadosTest(BaseRegravacaoTest):
    def test_placa_normalizada_e_dois_formatos(self):
        for digitada, guardada in (("abc-1234", "ABC1234"), (" abc 1d23 ", "ABC1D23")):
            self.assertEqual(self.criar_pelo_form(placa=digitada).status_code, 302, digitada)
            self.assertTrue(RegistroRegravacao.objects.filter(placa=guardada).exists(), guardada)

    def test_placa_invalida(self):
        self.assertContains(self.criar_pelo_form(placa="AB12"), "Placa inválida")
        self.assertEqual(RegistroRegravacao.objects.count(), 0)

    def test_chassi_17_sem_i_o_q_e_normaliza(self):
        self.assertContains(self.criar_pelo_form(chassi="123"), "Chassi inválido")
        self.assertContains(self.criar_pelo_form(chassi="9BD0000000000000I"), "Chassi inválido")
        self.criar_pelo_form(placa="CHA1A23", chassi="9bd00000000000001")
        self.assertEqual(RegistroRegravacao.objects.get(placa="CHA1A23").chassi, "9BD00000000000001")

    def test_ano_modelo_formato_faixa_e_ordem(self):
        for valido in ("2011/2012", "2015/2015", f"{date.today().year}/{date.today().year + 1}"):
            validar_ano_modelo(valido)
        for ruim in ("2011", "2011-2012", "20/12", "abcd/efgh", "2012/2011", "1949/1950", f"2020/{date.today().year + 2}"):
            with self.assertRaises(ValidationError, msg=ruim):
                validar_ano_modelo(ruim)
        self.assertContains(self.criar_pelo_form(ano_modelo="2012/2011"), "não pode ser menor")
        self.assertContains(self.criar_pelo_form(ano_modelo="2011"), "AAAA/AAAA")

    def test_pelo_menos_um_servico(self):
        resposta = self.criar_pelo_form(servico_chassi=None)
        self.assertContains(resposta, "Marque pelo menos um serviço")
        self.assertEqual(RegistroRegravacao.objects.count(), 0)
        self.assertEqual(self.criar_pelo_form(servico_motor="on", servico_chassi="on", placa="AMB1A23").status_code, 302)

    def test_data_concluida_nao_anterior_a_agendada_nem_futura(self):
        r = self.criar_pelo_form(data_agendada=self.dias(-2).isoformat(), data_concluida=self.dias(-5).isoformat())
        self.assertContains(r, "não pode ser anterior à data agendada")
        r = self.criar_pelo_form(data_concluida=self.dias(2).isoformat())
        self.assertContains(r, "não pode ser no futuro")
        self.assertEqual(RegistroRegravacao.objects.count(), 0)

    def test_recebido_exige_forma_e_data(self):
        r = self.criar_pelo_form(recebimento_situacao="recebido")
        self.assertContains(r, "Informe a forma de pagamento")
        self.assertContains(r, "Informe a data do recebimento")
        r = self.criar_pelo_form(recebimento_situacao="recebido", forma_pagamento="pix", data_recebimento=self.dias(3).isoformat())
        self.assertContains(r, "não pode ser no futuro")
        self.assertEqual(self.criar_pelo_form(recebimento_situacao="recebido", forma_pagamento="pix",
                                              data_recebimento=self.dias(0).isoformat(), placa="REC1A23").status_code, 302)

    def test_cor_outra_exige_descricao(self):
        self.assertContains(self.criar_pelo_form(cor="outra"), "Descreva a cor.")

    def test_so_cliente_placa_e_servico_sao_obrigatorios(self):
        r = self.criar_pelo_form(marca="", modelo="", ano_modelo="", cor="", chassi="", valor="", observacao="")
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(RegistroRegravacao.objects.get().valor)

    def test_proprietario_e_o_proprio_cliente(self):
        self.criar_pelo_form(proprietario_e_cliente="on", proprietario="Qualquer Coisa")
        r = RegistroRegravacao.objects.get()
        self.assertEqual((r.proprietario, r.nome_proprietario), ("", self.cliente.nome))


class StatusTest(BaseRegravacaoTest):
    def test_status_calculado(self):
        self.assertEqual(self.registro().status, S.SOLICITADA)
        self.assertEqual(self.registro(data_agendada=self.dias(2)).status, S.AGENDADA)
        self.assertEqual(self.registro(data_agendada=self.dias(-3), data_concluida=self.dias(-1)).status, S.AGENDADA)  # sem técnico
        self.assertEqual(self.registro(data_concluida=self.dias(-1), tecnico=self.tecnico).status, S.CONCLUIDA)
        self.assertEqual(self.registro(data_concluida=self.dias(-1), tecnico=self.tecnico, cancelada=True).status, S.CANCELADA)

    def test_historico_de_criacao_e_edicao(self):
        self.criar_pelo_form()
        r = RegistroRegravacao.objects.get()
        self.assertEqual(r.historico.first().tipo, "criacao")
        self.client.post(reverse("regravacao_editar", args=[r.pk]), self.dados_form(
            data_agendada=self.dias(3).isoformat(), valor="500.00", tecnico=self.tecnico.pk, parceiro=self.parceiro.pk))
        textos = " | ".join(h.valor_novo for h in r.historico.all())
        for esperado in ("valor: R$ 500,00", "técnico: Técnico de Teste", "parceiro: Parceiro de Teste", "data agendada", "status: Agendada"):
            self.assertIn(esperado, textos)
        self.assertEqual(r.historico.first().usuario, self.admin)

    def test_cancelar_exige_motivo_e_registra(self):
        r = self.registro()
        self.client.force_login(self.admin)
        self.assertContains(self.client.post(reverse("regravacao_cancelar", args=[r.pk]), {"motivo": ""}, follow=True), "motivo do cancelamento")
        self.client.post(reverse("regravacao_cancelar", args=[r.pk]), {"motivo": "Cliente desistiu"})
        r.refresh_from_db()
        self.assertEqual((r.status, r.motivo_cancelamento), (S.CANCELADA, "Cliente desistiu"))

    def test_valor_vazio_aceito_e_valor_negativo_nao(self):
        self.assertEqual(self.criar_pelo_form(valor="-5").status_code, 200)
        self.assertEqual(RegistroRegravacao.objects.count(), 0)

    def test_valor_decimal(self):
        self.criar_pelo_form(valor="1234.56")
        self.assertEqual(RegistroRegravacao.objects.get().valor, Decimal("1234.56"))
