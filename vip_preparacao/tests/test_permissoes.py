from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from financeiro.models import Recebimento
from vip_preparacao import regras
from vip_preparacao.models import FotoVip, RegistroVip

from .base import BaseVipTest, arquivo, jpeg


class AcessoTest(BaseVipTest):
    def test_anonimo_vai_para_o_login(self):
        r = self.registro()
        for url in (reverse("vip_lista"), reverse("vip_novo"), r.get_absolute_url(), reverse("vip_editar", args=[r.pk]),
                    reverse("vip_excluir", args=[r.pk]), reverse("vip_veiculo")):
            self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}", msg_prefix=url)
        for nome in ("vip_concluir", "vip_reabrir"):
            url = reverse(nome, args=[r.pk])
            self.assertEqual(self.client.post(url).status_code, 302, nome)
            self.assertEqual(RegistroVip.objects.get().status, "em_andamento")

    def test_usuario_sem_permissoes_recebe_403_em_tudo(self):
        get_user_model().objects.create_user("semperm", password="x")
        self.client.login(username="semperm", password="x")
        r = self.registro()
        for url in (reverse("vip_lista"), reverse("vip_novo"), r.get_absolute_url(), reverse("vip_editar", args=[r.pk]), reverse("vip_excluir", args=[r.pk])):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        for nome in ("vip_concluir", "vip_reabrir"):
            self.assertEqual(self.client.post(reverse(nome, args=[r.pk])).status_code, 403, nome)

    def test_item_no_menu_para_os_dois_perfis(self):
        for usuario in (self.admin, self.func):
            self.client.force_login(usuario)
            self.assertContains(self.client.get(reverse("inicio"), follow=True), reverse("vip_lista"))

    def test_funcionario_continua_sem_acesso_ao_financeiro(self):
        self.client.force_login(self.func)
        for nome in ("financeiro", "recebimento_lista", "contas_receber"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 403, nome)


class FuncionarioTest(BaseVipTest):
    """O funcionário cria, edita, conclui, reabre e exclui; só não altera o valor nem edita concluído por inteiro."""

    def test_funcionario_cria_edita_e_conclui(self):
        self.assertEqual(self.criar_pelo_form(usuario=self.func, placa="FUN1A23").status_code, 302)
        r = RegistroVip.objects.get(placa="FUN1A23")
        self.assertEqual(r.criado_por, self.func)
        self.client.post(reverse("vip_editar", args=[r.pk]), self.dados_form(registro=r, placa="FUN1A23", observacao="ok"))
        self.assertEqual(RegistroVip.objects.get().observacao, "ok")
        self.concluir(r, usuario=self.func)
        self.assertEqual(RegistroVip.objects.get().status, "concluido")
        self.assertEqual(Recebimento.objects.get().criado_por, self.func)

    def test_funcionario_reabre(self):
        r = self.registro()
        self.concluir(r, usuario=self.func)
        self.client.force_login(self.func)
        self.client.post(reverse("vip_reabrir", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.status, "em_andamento")
        self.assertIsNotNone(Recebimento.objects.get().estornado_em)

    def test_funcionario_exclui_registro_sem_atendimento(self):
        r = self.registro()
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("vip_excluir", args=[r.pk])).status_code, 200)
        self.client.post(reverse("vip_excluir", args=[r.pk]))
        self.assertEqual(RegistroVip.objects.count(), 0)

    def test_registro_que_ja_gerou_atendimento_nao_pode_ser_excluido_por_ninguem(self):
        r = self.registro()
        self.concluir(r)
        for usuario in (self.admin, self.func):
            self.client.force_login(usuario)
            resposta = self.client.post(reverse("vip_excluir", args=[r.pk]), follow=True)
            self.assertContains(resposta, "já foi concluído alguma vez")
            self.assertEqual(RegistroVip.objects.count(), 1)

    def test_exclusao_apaga_as_fotos_do_armazenamento(self):
        r = self.registro()
        regras.salvar_fotos(r, {("entrada", "placa"): (jpeg(), jpeg(40, 30))}, set(), self.admin)
        import os
        caminho = FotoVip.objects.get().imagem.path
        self.assertTrue(os.path.exists(caminho))
        self.client.force_login(self.admin)
        self.client.post(reverse("vip_excluir", args=[r.pk]))
        self.assertFalse(os.path.exists(caminho))
        self.assertEqual(FotoVip.objects.count(), 0)


class ValorEPermissoesCentralizadasTest(BaseVipTest):
    def test_somente_o_administrador_tem_alterar_valor_e_editar_concluido(self):
        self.assertTrue(self.admin.has_perm("vip_preparacao.alterar_valor_vip"))
        self.assertTrue(self.admin.has_perm("vip_preparacao.editar_concluido_vip"))
        self.assertFalse(self.func.has_perm("vip_preparacao.alterar_valor_vip"))
        self.assertFalse(self.func.has_perm("vip_preparacao.editar_concluido_vip"))
        for permissao in ("view", "add", "change", "delete"):
            self.assertTrue(self.func.has_perm(f"vip_preparacao.{permissao}_registrovip"), permissao)
        for permissao in ("concluir_vip", "reabrir_vip"):
            self.assertTrue(self.func.has_perm(f"vip_preparacao.{permissao}"), permissao)

    def test_botoes_do_detalhe_conforme_a_permissao(self):
        r = self.registro()
        self.client.force_login(self.func)
        html = self.client.get(r.get_absolute_url()).content.decode()
        for esperado in ("Marcar como concluído", "Editar", "Excluir"):
            self.assertIn(esperado, html)
        self.assertNotIn("Reabrir", html)          # ainda não está concluído


class RegistroConcluidoTest(BaseVipTest):
    def setUp(self):
        super().setUp()
        self.r = self.registro(valor=Decimal("150.00"))
        self.concluir(self.r)

    def test_administrador_edita_mas_cliente_servicos_e_valores_ficam_travados(self):
        self.client.force_login(self.admin)
        resposta = self.client.get(reverse("vip_editar", args=[self.r.pk]))
        self.assertContains(resposta, "Registro concluído.")
        self.assertContains(resposta, "os serviços e valores ficam travados")
        dados = self.dados_form(registro=self.r, placa=self.r.placa, cliente=self.outro_cliente.pk, observacao="ajuste")
        dados["itens-0-valor"], dados["itens-0-servico"] = "1.00", self.preparacao.pk     # tentativa de mexer nos itens
        self.client.post(reverse("vip_editar", args=[self.r.pk]), dados)
        self.r.refresh_from_db()
        item = self.r.itens.get()
        self.assertEqual((self.r.observacao, self.r.valor, item.servico, item.valor, self.r.cliente),
                         ("ajuste", Decimal("150.00"), self.vip, Decimal("150.00"), self.cliente))

    def test_funcionario_so_acrescenta_fotos_de_saida(self):
        self.client.force_login(self.func)
        pagina = self.client.get(reverse("vip_editar", args=[self.r.pk]))
        self.assertContains(pagina, "só acrescenta fotos de saída")
        self.assertNotContains(pagina, 'name="placa"')
        resposta = self.client.post(reverse("vip_editar", args=[self.r.pk]),
                                    {"foto_saida_frente": arquivo()}, follow=True)
        self.assertContains(resposta, "Fotos de saída salvas")
        self.assertEqual(set(self.r.fotos.values_list("momento", "posicao")), {("saida", "frente")})
        # tentar mexer em outros campos nesta tela não tem efeito
        self.client.post(reverse("vip_editar", args=[self.r.pk]), {"observacao": "hack", "valor": "1", "foto_entrada_placa": arquivo()})
        self.r.refresh_from_db()
        self.assertEqual((self.r.observacao, self.r.valor), ("", Decimal("150.00")))
        self.assertEqual(self.r.fotos.filter(momento="entrada").count(), 0)

    def test_funcionario_nao_troca_foto_de_saida_ja_existente(self):
        regras.salvar_fotos(self.r, {("saida", "frente"): (jpeg(), jpeg(40, 30))}, set(), self.admin)
        self.client.force_login(self.func)
        resposta = self.client.post(reverse("vip_editar", args=[self.r.pk]), {"foto_saida_frente": arquivo()})
        self.assertContains(resposta, "Já existe uma foto nesta posição")
        self.assertEqual(self.r.fotos.count(), 1)
