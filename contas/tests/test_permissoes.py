from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from cadastros.models import Cliente
from contas.permissoes import ADMINISTRADOR, FUNCIONARIO
from servicos.models import TipoServico


class PermissoesTest(TestCase):
    """Os grupos são criados automaticamente pelo post_migrate."""

    @classmethod
    def setUpTestData(cls):
        Usuario = get_user_model()
        cls.admin = Usuario.objects.create_user("admin", password="x")
        cls.admin.groups.add(Group.objects.get(name=ADMINISTRADOR))
        cls.func = Usuario.objects.create_user("func", password="x")
        cls.func.groups.add(Group.objects.get(name=FUNCIONARIO))
        cls.servico = TipoServico.objects.create(
            nome="Teste", categoria=TipoServico.Categoria.LIMPEZA, valor_padrao="10.00",
        )
        cls.cliente = Cliente.objects.create(nome="Cli", telefone="1")

    # --- usuário não logado ---
    def test_anonimo_e_redirecionado_ao_login(self):
        urls = [
            reverse("inicio"), reverse("cliente_lista"), reverse("cliente_novo"),
            reverse("cliente_detalhe", args=[self.cliente.pk]), reverse("aluno_lista"),
            reverse("veiculo_lista"), reverse("servico_lista"), reverse("servico_novo"),
            reverse("servico_editar", args=[self.servico.pk]),
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertRedirects(resp, f"{reverse('login')}?next={url}", msg_prefix=url)

    # --- funcionário ---
    def test_funcionario_nao_edita_tipo_de_servico(self):
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("servico_novo")).status_code, 403)
        self.assertEqual(self.client.get(reverse("servico_editar", args=[self.servico.pk])).status_code, 403)
        resp = self.client.post(
            reverse("servico_editar", args=[self.servico.pk]),
            {"nome": "Alterado", "categoria": "limpeza", "valor_padrao": "999", "ativo": "on"},
        )
        self.assertEqual(resp.status_code, 403)
        self.servico.refresh_from_db()
        self.assertEqual(self.servico.nome, "Teste")

    def test_funcionario_nao_exclui_tipo_de_servico(self):
        self.client.force_login(self.func)
        self.assertEqual(self.client.post(reverse("servico_excluir", args=[self.servico.pk])).status_code, 403)
        self.assertTrue(TipoServico.objects.filter(pk=self.servico.pk).exists())

    def test_funcionario_consulta_servicos_e_cadastra_clientes(self):
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("servico_lista")).status_code, 200)
        self.assertEqual(self.client.get(reverse("servico_detalhe", args=[self.servico.pk])).status_code, 200)
        resp = self.client.post(reverse("cliente_novo"), {
            "nome": "Novo", "telefone": "(11) 90000-0000", "data_cadastro": "2026-01-01",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Cliente.objects.filter(nome="Novo").exists())

    # --- administrador ---
    def test_administrador_edita_tipo_de_servico(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("servico_editar", args=[self.servico.pk]),
            {"nome": "Alterado", "categoria": "limpeza", "valor_padrao": "55.50", "ativo": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        self.servico.refresh_from_db()
        self.assertEqual(self.servico.nome, "Alterado")

    def test_login_com_credenciais_corretas(self):
        resp = self.client.post(reverse("login"), {"username": "func", "password": "x"})
        self.assertRedirects(resp, reverse("inicio"))

    def test_grupos_criados_automaticamente(self):
        self.assertEqual(Group.objects.filter(name__in=[ADMINISTRADOR, FUNCIONARIO]).count(), 2)
        func = Group.objects.get(name=FUNCIONARIO)
        codenames = set(func.permissions.values_list("codename", flat=True))
        self.assertIn("view_tiposervico", codenames)
        self.assertNotIn("change_tiposervico", codenames)
        self.assertNotIn("add_tiposervico", codenames)
