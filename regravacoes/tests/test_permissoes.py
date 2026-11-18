from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from contas.permissoes import ACESSO_POR_PERFIL, ADMINISTRADOR, FUNCIONARIO
from regravacoes import regras
from regravacoes.documentos import emissao
from regravacoes.models import ConfiguracaoEmpresa, DocumentoEmitido, Parceiro, RegistroRegravacao, Tecnico

from .base import BaseRegravacaoTest, arquivo_pdf

D = Decimal
PADRAO = dict(ACESSO_POR_PERFIL)                                                    # o mapa de produção
LIBERADO = {**PADRAO, FUNCIONARIO: ("clientes", "servicos", "vip", "regravacoes")}  # uma linha a mais


def recarregar(usuario):
    """Usuário "novo" do banco (o perfil é lido por requisição e guardado por objeto)."""
    return get_user_model().objects.get(pk=usuario.pk)


@override_settings(ACESSO_POR_PERFIL=PADRAO)
class SoOAdministradorPorPadraoTest(BaseRegravacaoTest):
    def setUp(self):
        super().setUp()
        self.r = self.completa()
        self.client.force_login(self.func)

    def test_funcionario_recebe_403_em_todas_as_telas_e_downloads(self):
        doc, _ = emissao.emitir(self.r, DocumentoEmitido.Tipo.DECLARACAO, self.admin)
        anexo = self.r.anexos.first()
        urls = [reverse("regravacao_lista"), reverse("regravacao_novo"), self.r.get_absolute_url(), reverse("regravacao_editar", args=[self.r.pk]),
                reverse("regravacao_excluir", args=[self.r.pk]), reverse("parceiro_lista"), reverse("parceiro_novo"), reverse("tecnico_lista"),
                reverse("tecnico_novo"), reverse("empresa"), reverse("documento_baixar", args=[doc.pk]),
                reverse("anexo_baixar", args=[anexo.pk, "arquivo"]), reverse("regravacao_veiculo")]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        for nome, args in (("regravacao_concluir", [self.r.pk]), ("regravacao_reabrir", [self.r.pk]), ("regravacao_cancelar", [self.r.pk]),
                           ("documento_emitir", [self.r.pk, "declaracao"]), ("parceiro_ativo", [self.parceiro.pk]), ("tecnico_ativo", [self.tecnico.pk])):
            self.assertEqual(self.client.post(reverse(nome, args=args), {}).status_code, 403, nome)

    def test_menu_do_funcionario_nao_tem_regravacoes_e_o_do_administrador_tem(self):
        html = self.client.get(reverse("vip_lista")).content.decode()
        for nome in ("regravacao_lista", "parceiro_lista", "tecnico_lista"):
            self.assertNotIn(f'href="{reverse(nome)}"', html, nome)
        self.client.force_login(self.admin)
        html = self.client.get(reverse("inicio")).content.decode()
        menu = html[html.index('id="menu"'):html.index("</aside>")]
        for nome in ("regravacao_lista", "parceiro_lista", "tecnico_lista"):
            self.assertIn(f'href="{reverse(nome)}"', menu, nome)

    def test_administrador_acessa_tudo(self):
        self.client.force_login(self.admin)
        for url in (reverse("regravacao_lista"), reverse("regravacao_novo"), self.r.get_absolute_url(), reverse("parceiro_lista"),
                    reverse("tecnico_lista"), reverse("empresa"), reverse("parceiro_novo"), reverse("tecnico_novo")):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_anonimo_vai_para_o_login(self):
        self.client.logout()
        for url in (reverse("regravacao_lista"), self.r.get_absolute_url(), reverse("empresa")):
            self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}", msg_prefix=url)

    def test_usuario_sem_grupo_recebe_403(self):
        self.client.force_login(get_user_model().objects.create_user("semgrupo", password="x"))
        self.assertEqual(self.client.get(reverse("regravacao_lista")).status_code, 403)


@override_settings(ACESSO_POR_PERFIL=LIBERADO)
class LiberadoParaOFuncionarioTest(BaseRegravacaoTest):
    """Mudar UMA linha na central de acesso muda o comportamento: as permissões finas passam a valer."""

    def setUp(self):
        super().setUp()
        self.client.force_login(recarregar(self.func))

    def test_funcionario_ve_cria_edita_conclui_anexa_e_emite(self):
        self.assertEqual(self.client.get(reverse("regravacao_lista")).status_code, 200)
        self.assertContains(self.client.get(reverse("vip_lista")), reverse("regravacao_lista"))           # aparece no menu
        completos = dict(chassi="9BD00000000000001", proprietario="Fulano de Teste")      # dados que a declaração exige
        self.assertEqual(self.criar_pelo_form(usuario=recarregar(self.func), placa="FUN1A23", **completos).status_code, 302)
        r = RegistroRegravacao.objects.get(placa="FUN1A23")
        self.assertEqual(r.criado_por, self.func)
        self.client.post(reverse("regravacao_editar", args=[r.pk]), self.dados_form(placa="FUN1A23", observacao="ok", anexo_autorizacao_chassi=arquivo_pdf(), **completos))
        r.refresh_from_db()
        self.assertEqual(r.observacao, "ok")
        self.assertEqual(r.anexos.count(), 1)
        self.client.post(reverse("regravacao_concluir", args=[r.pk]), {"data_concluida": self.dias(-1).isoformat(), "tecnico": self.tecnico.pk, "situacao": "pendente"})
        r.refresh_from_db()
        self.assertEqual(r.status, "concluida")
        resposta = self.client.post(reverse("documento_emitir", args=[r.pk, "declaracao"]))
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(DocumentoEmitido.objects.count(), 1)

    def test_funcionario_nao_altera_valor(self):
        self.criar_pelo_form(usuario=recarregar(self.func), placa="VAL1A23", valor="999.00")
        self.assertIsNone(RegistroRegravacao.objects.get(placa="VAL1A23").valor)                          # ignorado no servidor
        r = self.registro(valor=D("400.00"), placa="VAL2A23")
        self.client.post(reverse("regravacao_editar", args=[r.pk]), self.dados_form(placa="VAL2A23", valor="1.00"))
        r.refresh_from_db()
        self.assertEqual(r.valor, D("400.00"))
        pagina = self.client.get(reverse("regravacao_editar", args=[r.pk]))
        self.assertRegex(pagina.content.decode(), r'<input[^>]*name="valor"[^>]*disabled')
        self.assertContains(pagina, "Só o Administrador define o valor")

    def test_funcionario_nao_gerencia_tecnicos_parceiros_nem_empresa(self):
        self.assertEqual(self.client.get(reverse("tecnico_lista")).status_code, 200)                      # só consulta
        self.assertEqual(self.client.get(reverse("parceiro_lista")).status_code, 200)
        for nome in ("tecnico_novo", "parceiro_novo", "empresa"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 403, nome)
        self.assertEqual(self.client.get(reverse("tecnico_editar", args=[self.tecnico.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("parceiro_editar", args=[self.parceiro.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("tecnico_ativo", args=[self.tecnico.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("parceiro_ativo", args=[self.parceiro.pk])).status_code, 403)
        pagina = self.client.get(reverse("regravacao_novo")).content.decode()
        self.assertNotIn("Cadastrar técnico", pagina)
        self.assertNotIn("Cadastrar novo parceiro", pagina)
        self.assertNotIn("Total faturado", self.client.get(self.parceiro.get_absolute_url()).content.decode())

    def test_funcionario_nao_exclui_nao_reabre_nem_edita_o_lancado(self):
        r = self.registro(data_concluida=self.dias(-1), tecnico=self.tecnico, recebimento_situacao="recebido",
                          forma_pagamento="pix", data_recebimento=self.dias(0))
        regras.lancar(r, self.admin)
        self.assertEqual(self.client.get(reverse("regravacao_excluir", args=[r.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("regravacao_reabrir", args=[r.pk])).status_code, 403)
        resposta = self.client.get(reverse("regravacao_editar", args=[r.pk]), follow=True)
        self.assertContains(resposta, "está travada")                                                       # só o Administrador edita
        self.client.post(reverse("regravacao_editar", args=[r.pk]), self.dados_form(placa=r.placa, observacao="hack"))
        r.refresh_from_db()
        self.assertEqual(r.observacao, "")
        detalhe = self.client.get(r.get_absolute_url()).content.decode()
        self.assertNotIn("Reabrir", detalhe)
        self.assertNotIn("Excluir", detalhe)
        self.assertIn("Concluir", self.client.get(self.registro(placa="OUT1A23").get_absolute_url()).content.decode())

    def test_funcionario_nao_baixa_documento_de_outro_modulo_oculto_mas_baixa_o_deste(self):
        r = self.completa()
        doc, _ = emissao.emitir(r, DocumentoEmitido.Tipo.DECLARACAO, self.admin)
        self.assertEqual(self.client.get(reverse("documento_baixar", args=[doc.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("financeiro")).status_code, 403)                        # o resto continua oculto

    def test_voltando_ao_padrao_o_funcionario_perde_o_acesso(self):
        self.assertEqual(self.client.get(reverse("regravacao_lista")).status_code, 200)
        with override_settings(ACESSO_POR_PERFIL=PADRAO):
            self.client.force_login(recarregar(self.func))
            self.assertEqual(self.client.get(reverse("regravacao_lista")).status_code, 403)


@override_settings(ACESSO_POR_PERFIL=PADRAO)
class PrivacidadeDosEndpointsTest(BaseRegravacaoTest):
    def test_veiculo_por_placa_devolve_so_o_necessario(self):
        self.client.force_login(self.admin)
        dados = self.client.get(reverse("regravacao_veiculo"), {"placa": "abc-1234"}).json()
        self.assertEqual(set(dados), {"encontrado", "marca", "modelo", "ano_modelo", "chassi", "cor", "cor_outra"})
        self.assertEqual((dados["encontrado"], dados["marca"], dados["ano_modelo"]), (True, "Fiat", "2012/2012"))
        self.assertNotIn(self.cliente.nome, str(dados))
        self.assertEqual(self.client.get(reverse("regravacao_veiculo"), {"placa": "ZZZ9999"}).json(), {"encontrado": False})

    def test_empresa_so_o_administrador_edita_e_a_logo_fica_no_banco(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        self.client.force_login(self.admin)
        imagem = BytesIO()
        Image.new("RGB", (100, 50), (10, 70, 100)).save(imagem, "PNG")
        dados = {"razao_social": "Outra Empresa Ltda", "cnpj": "11.222.333/0001-81", "endereco": "Rua X", "telefones": "1", "cidade": "Y",
                 "rodape": "", "responsavel_recibo_nome": "Fulano", "responsavel_recibo_funcao": "", "servico_motor": self.srv_motor.pk,
                 "servico_chassi": self.srv_chassi.pk, "servico_motor_chassi": self.srv_ambos.pk,
                 "logo_nova": SimpleUploadedFile("logo.png", imagem.getvalue(), content_type="image/png")}
        self.client.post(reverse("empresa"), dados)
        cfg = ConfiguracaoEmpresa.obter()
        self.assertEqual(cfg.razao_social, "Outra Empresa Ltda")
        self.assertTrue(bytes(cfg.logo).startswith(b"\x89PNG"))
        invalida = dict(dados, logo_nova=SimpleUploadedFile("logo.png", b"nao e imagem", content_type="image/png"))
        self.assertContains(self.client.post(reverse("empresa"), invalida), "não é uma imagem válida")

    def test_botao_criar_servicos_padrao_nao_altera_existentes(self):
        from servicos.models import TipoServico
        cfg = ConfiguracaoEmpresa.obter()
        cfg.servico_motor = cfg.servico_chassi = cfg.servico_motor_chassi = None
        cfg.save()
        antes = TipoServico.objects.get(pk=self.srv_motor.pk).valor_padrao
        self.client.force_login(self.admin)
        self.client.post(reverse("empresa"), {"criar_servicos": "1"})
        cfg.refresh_from_db()
        self.assertEqual(cfg.servico_motor, self.srv_motor)                  # reaproveitou o que já existia
        self.assertEqual(TipoServico.objects.get(pk=self.srv_motor.pk).valor_padrao, antes)
        self.assertEqual(TipoServico.objects.filter(nome="Regravação de motor").count(), 1)
