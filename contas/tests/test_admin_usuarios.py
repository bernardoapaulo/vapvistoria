"""Cadastro de usuários pelo painel /admin/: o Administrador cria login e senha e escolhe o perfil."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from contas.permissoes import ACESSO_POR_PERFIL, ADMINISTRADOR, FUNCIONARIO

Usuario = get_user_model()


@override_settings(ACESSO_POR_PERFIL=ACESSO_POR_PERFIL)
class CadastroDeUsuariosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_user("adm", password="x", is_staff=True)
        cls.admin.groups.add(Group.objects.get(name=ADMINISTRADOR))
        cls.func = Usuario.objects.create_user("func", password="x")
        cls.func.groups.add(Group.objects.get(name=FUNCIONARIO))
        cls.super = Usuario.objects.create_superuser("chefe", password="x")

    def setUp(self):
        self.client.force_login(self.admin)

    def criar(self, username="novo_func", senha="Senha#Forte2026"):
        return self.client.post(reverse("admin:auth_user_add"), {
            "username": username, "password1": senha, "password2": senha, "usable_password": "true"})

    def test_administrador_ve_usuarios_e_grupos_no_painel(self):
        pagina = self.client.get(reverse("admin:index"))
        self.assertContains(pagina, "Usuários")
        self.assertNotContains(pagina, "Você não tem permissão para ver ou editar nada")
        self.assertContains(self.client.get(reverse("admin:auth_user_changelist")), "func")

    def test_cria_funcionario_com_login_e_senha_e_ele_entra_no_vip(self):
        resposta = self.criar()
        novo = Usuario.objects.get(username="novo_func")
        self.assertRedirects(resposta, reverse("admin:auth_user_change", args=[novo.pk]))
        self.assertTrue(novo.check_password("Senha#Forte2026"))
        # segundo passo da tela: escolher o perfil (grupo) e salvar
        self.client.post(reverse("admin:auth_user_change", args=[novo.pk]), {
            "username": "novo_func", "first_name": "Novo", "last_name": "Funcionário", "email": "", "is_active": "on",
            "groups": [Group.objects.get(name=FUNCIONARIO).pk],
            "last_login_0": "", "last_login_1": "", "date_joined_0": "2026-01-01", "date_joined_1": "00:00:00"})
        novo.refresh_from_db()
        self.assertEqual(list(novo.groups.values_list("name", flat=True)), [FUNCIONARIO])
        self.assertFalse(novo.is_staff or novo.is_superuser)
        # o novo Funcionário entra pelo login do sistema e cai no Vip/Preparação
        self.client.logout()
        resposta = self.client.post(reverse("login"), {"username": "novo_func", "password": "Senha#Forte2026"}, follow=True)
        self.assertEqual(resposta.redirect_chain[-1][0], reverse("vip_lista"))
        self.assertEqual(self.client.get(reverse("financeiro")).status_code, 403)

    def test_senha_fraca_e_recusada(self):
        resposta = self.criar(username="fraco", senha="12345678")
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="fraco").exists())

    def test_administrador_comum_nao_se_da_superpoderes(self):
        self.criar()
        novo = Usuario.objects.get(username="novo_func")
        self.client.post(reverse("admin:auth_user_change", args=[novo.pk]), {
            "username": "novo_func", "first_name": "", "last_name": "", "email": "", "is_active": "on",
            "is_superuser": "on", "is_staff": "on", "groups": [Group.objects.get(name=FUNCIONARIO).pk],
            "user_permissions": [1], "last_login_0": "", "last_login_1": "", "date_joined_0": "2026-01-01", "date_joined_1": "00:00:00"})
        novo.refresh_from_db()
        self.assertFalse(novo.is_superuser)                       # campo somente leitura: o valor enviado é ignorado
        self.assertEqual(novo.user_permissions.count(), 0)

    def test_nao_mexe_em_superusuario_nem_exclui_usuario(self):
        resposta = self.client.post(reverse("admin:auth_user_change", args=[self.super.pk]), {"username": "chefe", "email": "x@y.z"})
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:auth_user_delete", args=[self.func.pk])).status_code, 403)
        self.assertTrue(Usuario.objects.filter(pk=self.func.pk).exists())

    def test_funcionario_nao_abre_o_painel(self):
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:auth_user_add")).status_code, 403)
