from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from atendimentos.models import Atendimento

from .base import BaseAtendimentoTest


class ValidacaoPorCategoriaTest(BaseAtendimentoTest):
    def _erros(self, **campos):
        a = Atendimento(**{"cliente": self.cliente, "valor_cobrado": Decimal("100"), **campos})
        with self.assertRaises(ValidationError) as ctx:
            a.full_clean()
        return ctx.exception.message_dict

    def test_vistoria_exige_veiculo(self):
        erros = self._erros(tipo_servico=self.vistoria)
        self.assertIn("exige um veículo", erros["veiculo"][0])

    def test_veiculo_deve_ser_do_cliente(self):
        erros = self._erros(tipo_servico=self.vistoria, veiculo=self.veiculo_outro)
        self.assertIn("não pertence ao cliente", erros["veiculo"][0])

    def test_limpeza_nao_aceita_aluno(self):
        erros = self._erros(tipo_servico=self.limpeza, veiculo=self.veiculo, aluno=self.aluno)
        self.assertIn("aluno", erros)

    def test_capacitacao_exige_aluno(self):
        erros = self._erros(tipo_servico=self.curso)
        self.assertIn("Informe o aluno", erros["aluno"][0])

    def test_capacitacao_nao_aceita_veiculo(self):
        erros = self._erros(tipo_servico=self.curso, aluno=self.aluno, veiculo=self.veiculo)
        self.assertIn("Veículo não se aplica", erros["veiculo"][0])

    def test_combinacoes_validas(self):
        Atendimento(cliente=self.cliente, tipo_servico=self.vistoria, veiculo=self.veiculo,
                    valor_cobrado=Decimal("1")).full_clean()
        Atendimento(cliente=self.cliente, tipo_servico=self.curso, aluno=self.aluno,
                    valor_cobrado=Decimal("1")).full_clean()

    def test_desconto_maior_que_valor(self):
        erros = self._erros(tipo_servico=self.vistoria, veiculo=self.veiculo, desconto=Decimal("200"))
        self.assertIn("desconto", erros)


class ValorSnapshotTest(BaseAtendimentoTest):
    def test_mudar_valor_padrao_nao_altera_atendimento_antigo(self):
        a = self.criar()
        self.vistoria.valor_padrao = Decimal("999.00")
        self.vistoria.save()
        a.refresh_from_db()
        self.assertEqual(a.valor_cobrado, Decimal("250.00"))

    def test_formulario_usa_valor_padrao_quando_em_branco(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("atendimento_novo"), self.dados_form(valor_cobrado=""))
        self.assertEqual(Atendimento.objects.get().valor_cobrado, Decimal("250.00"))

    def test_formulario_mostra_erros_em_portugues(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("atendimento_novo"), self.dados_form(veiculo=self.veiculo_outro.pk))
        self.assertContains(resp, "não pertence ao cliente escolhido")
        resp = self.client.post(reverse("atendimento_novo"), {})
        self.assertContains(resp, "Selecione o cliente")
        self.assertContains(resp, "Selecione o tipo de serviço")
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_formulario_entrega_dados_para_o_javascript(self):
        """O JS filtra veículos por cliente e alterna veículo/aluno usando estes atributos."""
        self.client.force_login(self.admin)
        html = self.client.get(reverse("atendimento_novo")).content.decode()
        self.assertIn(f'data-cliente="{self.cliente.pk}"', html)          # veículo -> proprietário
        self.assertIn('data-exige="veiculo"', html)                        # vistoria
        self.assertIn('data-exige="aluno"', html)                          # capacitação
        self.assertIn('data-valor="250.00"', html)                         # valor padrão
        self.assertIn('data-campo="veiculo"', html)
        self.assertIn("atendimento_form.js", html)

    def test_atalho_novo_atendimento_a_partir_do_veiculo(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("atendimento_novo"), {"veiculo": self.veiculo.pk})
        self.assertEqual(resp.context["form"].initial["cliente"], self.cliente.pk)

    def test_totais_ignoram_cancelados(self):
        pago = self.criar(desconto=Decimal("50"))
        self.receber(pago)
        self.criar(status="cancelado")
        totais = Atendimento.objects.totais()
        self.assertEqual(totais["total"], Decimal("200"))
        self.assertEqual(totais["pago"], Decimal("200"))
        self.assertEqual(totais["em_aberto"], Decimal("0"))
