from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from cadastros.models import Cliente, Veiculo
from contas.permissoes import ADMINISTRADOR


class TelasCadastroTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("adm", password="x")
        cls.user.groups.add(Group.objects.get(name=ADMINISTRADOR))
        cls.cliente = Cliente.objects.create(
            nome="Maria Teste", telefone="(11) 90000-0000", cpf_cnpj="529.982.247-25", email="m@exemplo.com",
        )
        Veiculo.objects.create(placa="ABC1234", marca="Fiat", modelo="Uno", ano=2012, cor="Branco",
                               proprietario=cls.cliente)

    def setUp(self):
        self.client.force_login(self.user)

    def test_busca_de_clientes(self):
        resp = self.client.get(reverse("cliente_lista"), {"q": "maria"})
        self.assertContains(resp, "Maria Teste")
        resp = self.client.get(reverse("cliente_lista"), {"q": "inexistente"})
        self.assertContains(resp, "Nenhum cliente encontrado")

    def test_paginacao(self):
        for i in range(20):
            Cliente.objects.create(nome=f"Cliente {i:02d}", telefone="1")
        resp = self.client.get(reverse("cliente_lista"))
        self.assertEqual(len(resp.context["object_list"]), 15)
        self.assertTrue(resp.context["is_paginated"])

    def test_listagem_nao_expoe_cpf_nem_email(self):
        resp = self.client.get(reverse("cliente_lista"))
        self.assertNotContains(resp, "529.982.247-25")
        self.assertNotContains(resp, "m@exemplo.com")

    def test_detalhe_mostra_veiculos_e_cpf_mascarado(self):
        resp = self.client.get(reverse("cliente_detalhe", args=[self.cliente.pk]))
        self.assertContains(resp, "ABC1234")
        self.assertContains(resp, "***.982.247-**")
        self.assertNotContains(resp, "529.982.247-25")
        self.assertContains(resp, "Histórico de serviços")

    def test_excluir_cliente_com_veiculo_e_bloqueado(self):
        resp = self.client.post(reverse("cliente_excluir", args=[self.cliente.pk]))
        self.assertContains(resp, "não pode ser excluído")
        self.assertTrue(Cliente.objects.filter(pk=self.cliente.pk).exists())

    def test_excluir_cliente_sem_veiculo(self):
        outro = Cliente.objects.create(nome="Sem carro", telefone="1")
        resp = self.client.post(reverse("cliente_excluir", args=[outro.pk]))
        self.assertRedirects(resp, reverse("cliente_lista"))
        self.assertFalse(Cliente.objects.filter(pk=outro.pk).exists())

    def test_formulario_mostra_erros_em_portugues(self):
        resp = self.client.post(reverse("veiculo_novo"), {"placa": "ZZ", "ano": "abc"})
        self.assertContains(resp, "Placa inválida")
        self.assertContains(resp, "Informe a marca.")
