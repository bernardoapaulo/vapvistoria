from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import TestCase

from cadastros.forms import VeiculoForm
from cadastros.models import Aluno, Cliente, Veiculo
from cadastros.validators import mascarar_cpf_cnpj, validar_cpf_cnpj, validar_placa


class ValidadoresTest(TestCase):
    def test_placa_formato_antigo_e_mercosul(self):
        validar_placa("ABC1234")
        validar_placa("abc-1234")
        validar_placa("BRA2E19")

    def test_placa_invalida(self):
        for placa in ["ABC12", "1234ABC", "ABCD123", "AB1C234"]:
            with self.assertRaises(ValidationError, msg=placa):
                validar_placa(placa)

    def test_cpf_e_cnpj_validos(self):
        validar_cpf_cnpj("529.982.247-25")
        validar_cpf_cnpj("11.222.333/0001-81")

    def test_cpf_e_cnpj_invalidos(self):
        for doc in ["111.111.111-11", "123.456.789-00", "11.222.333/0001-80", "123"]:
            with self.assertRaises(ValidationError, msg=doc):
                validar_cpf_cnpj(doc)

    def test_mascara_lgpd(self):
        self.assertEqual(mascarar_cpf_cnpj("52998224725"), "***.982.247-**")


class ModelosTest(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nome="Cliente Teste", telefone="(11) 90000-0000")

    def test_str_dos_modelos(self):
        self.assertEqual(str(self.cliente), "Cliente Teste")
        aluno = Aluno.objects.create(nome="Aluno Teste", celular="1", cliente=self.cliente)
        self.assertEqual(str(aluno), "Aluno Teste")

    def test_aluno_vinculo_opcional_e_set_null(self):
        aluno = Aluno.objects.create(nome="Aluno", celular="1", cliente=self.cliente)
        self.cliente.delete()
        aluno.refresh_from_db()
        self.assertIsNone(aluno.cliente)

    def _dados_veiculo(self, **extra):
        dados = {"placa": "abc1234", "marca": "Fiat", "modelo": "Uno", "ano": 2012,
                 "cor": "Branco", "chassi": "", "proprietario": self.cliente.pk, "observacoes": ""}
        dados.update(extra)
        return dados

    def test_placa_salva_em_maiusculas(self):
        form = VeiculoForm(self._dados_veiculo(placa="abc-1234"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().placa, "ABC1234")

    def test_placa_unica(self):
        VeiculoForm(self._dados_veiculo()).save()
        form = VeiculoForm(self._dados_veiculo(placa="ABC1234"))
        self.assertFalse(form.is_valid())
        self.assertIn("Já existe", form.errors["placa"][0])

    def test_placa_invalida_no_formulario(self):
        form = VeiculoForm(self._dados_veiculo(placa="XXXX"))
        self.assertFalse(form.is_valid())
        self.assertIn("Placa inválida", form.errors["placa"][0])

    def test_chassi_deve_ter_17_caracteres(self):
        form = VeiculoForm(self._dados_veiculo(chassi="123"))
        self.assertFalse(form.is_valid())
        self.assertIn("chassi", form.errors)

    def test_cliente_com_veiculo_nao_pode_ser_excluido(self):
        VeiculoForm(self._dados_veiculo()).save()
        with self.assertRaises(ProtectedError):
            self.cliente.delete()
