import os
from io import BytesIO
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from regravacoes import anexos
from regravacoes.models import AnexoRegravacao

from .base import BaseRegravacaoTest, Tipo, arquivo_jpeg, arquivo_pdf, pdf_minimo
from vip_preparacao.tests.base import jpeg
from vip_preparacao.tests.test_fotos import exif_com_gps_e_orientacao


class ValidacaoDosAnexosTest(BaseRegravacaoTest):
    def test_aceita_pdf_e_imagens(self):
        self.assertEqual(anexos.processar(arquivo_pdf())["content_type"], "application/pdf")
        for formato in ("JPEG", "PNG", "WEBP"):
            dados = anexos.processar(SimpleUploadedFile("f", jpeg(formato=formato)))
            self.assertEqual(Image.open(BytesIO(dados["conteudo"])).format, "JPEG", formato)
            self.assertEqual(dados["content_type"], "image/jpeg")

    def test_rejeita_o_que_nao_e_pdf_nem_imagem_mesmo_com_extensao_certa(self):
        ruins = [(b"texto qualquer", "a.pdf"), (b"%PDF-1.4 fake sem fim", "b.pdf"), (b"", "c.jpg"),
                 (b"MZ\x90\x00executavel", "d.png"), (b"<html><script>alert(1)</script></html>", "e.pdf")]
        for conteudo, nome in ruins:
            with self.assertRaises(Exception, msg=nome) as erro:
                anexos.processar(SimpleUploadedFile(nome, conteudo))
            self.assertTrue(any(t in str(erro.exception) for t in ("PDF", "imagem", "Envie")), nome)

    def test_rejeita_pdf_com_script_e_pdf_protegido(self):
        com_js = pdf_minimo().replace(b"%%EOF", b"/JavaScript (app.alert(1))\n%%EOF")
        with self.assertRaises(Exception) as erro:
            anexos.processar(SimpleUploadedFile("js.pdf", com_js))
        self.assertIn("scripts", str(erro.exception))

    def test_rejeita_arquivo_grande_demais(self):
        with mock.patch.dict(os.environ, {"REGRAVACAO_ANEXO_MAX_MB": "0.0001"}):
            with self.assertRaises(Exception) as erro:
                anexos.processar(arquivo_pdf())
        self.assertIn("muito grande", str(erro.exception))
        self.assertEqual(anexos.limite_bytes(), 10 * 1024 * 1024)       # padrão: 10 MB, configurável

    def test_imagem_perde_exif_e_gps_e_tem_orientacao_corrigida(self):
        original = jpeg(200, 100, exif=exif_com_gps_e_orientacao(orientacao=6))
        dados = anexos.processar(SimpleUploadedFile("f.jpg", original))
        imagem = Image.open(BytesIO(dados["conteudo"]))
        self.assertEqual(dict(imagem.getexif()), {})
        self.assertNotIn(b"Fabricante Secreto", dados["conteudo"])
        self.assertEqual(imagem.size, (100, 200))
        self.assertIsNotNone(dados["miniatura"])


class AnexosNoRegistroTest(BaseRegravacaoTest):
    def _post(self, registro, **arquivos):
        self.client.force_login(self.admin)
        dados = self.dados_form(servico_motor="on" if registro.servico_motor else None,
                                servico_chassi="on" if registro.servico_chassi else None, placa=registro.placa, **arquivos)
        return self.client.post(reverse("regravacao_editar", args=[registro.pk]), dados)

    def test_autorizacao_exigida_conforme_o_servico(self):
        self.assertEqual(self.registro(servico_motor=True, servico_chassi=False).anexos_exigidos, [Tipo.AUTORIZACAO_MOTOR])
        self.assertEqual(self.registro(servico_motor=False, servico_chassi=True).anexos_exigidos, [Tipo.AUTORIZACAO_CHASSI])
        self.assertEqual(self.registro(servico_motor=True, servico_chassi=True).anexos_exigidos,
                         [Tipo.AUTORIZACAO_MOTOR, Tipo.AUTORIZACAO_CHASSI])

    def test_pendente_ate_anexar(self):
        r = self.registro(servico_motor=True, servico_chassi=True)
        self.assertEqual(r.anexos_pendentes, [Tipo.AUTORIZACAO_MOTOR, Tipo.AUTORIZACAO_CHASSI])
        self._post(r, anexo_autorizacao_motor=arquivo_pdf())
        r.refresh_from_db()
        self.assertEqual(r.anexos_pendentes, [Tipo.AUTORIZACAO_CHASSI])
        self.client.force_login(self.admin)
        lista = self.client.get(reverse("regravacao_lista")).content.decode()
        self.assertIn("1 pendente", lista)                                  # ícone + texto, nunca só cor
        self.assertIn("Pendente (exigida)", self.client.get(r.get_absolute_url()).content.decode())

    def test_envia_na_criacao_e_rejeita_arquivo_invalido_com_mensagem(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("regravacao_novo"), self.dados_form(
            anexo_documento_veiculo=SimpleUploadedFile("x.pdf", b"nao sou pdf", content_type="application/pdf")))
        self.assertContains(r, "não é um PDF nem uma imagem válida")
        self.assertEqual(AnexoRegravacao.objects.count(), 0)
        self.client.post(reverse("regravacao_novo"), self.dados_form(anexo_documento_veiculo=arquivo_jpeg(), anexo_laudo_ecv=arquivo_pdf()))
        self.assertEqual(sorted(AnexoRegravacao.objects.values_list("tipo", flat=True)), ["documento_veiculo", "laudo_ecv"])

    def test_trocar_e_remover_apagam_o_arquivo_antigo(self):
        r = self.registro()
        with self.captureOnCommitCallbacks(execute=True):
            self._post(r, anexo_laudo_ecv=arquivo_pdf(texto="primeiro"))
        antigo = AnexoRegravacao.objects.get().arquivo.path
        self.assertTrue(os.path.exists(antigo))
        with self.captureOnCommitCallbacks(execute=True):
            self._post(r, anexo_laudo_ecv=arquivo_pdf(texto="segundo"))
        self.assertFalse(os.path.exists(antigo))
        self.assertEqual(AnexoRegravacao.objects.count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            self._post(r, remover_anexo_laudo_ecv="on")
        self.assertEqual(AnexoRegravacao.objects.count(), 0)
        self.assertEqual([f for _, _, fs in os.walk(self.pasta) for f in fs], [])
        textos = " | ".join(h.valor_novo for h in r.historico.filter(tipo="anexo"))
        self.assertIn("anexado", textos)
        self.assertIn("removido", textos)

    def test_nome_nao_adivinhavel_e_fora_de_pastas_publicas(self):
        r = self.registro()
        self._post(r, anexo_laudo_ecv=SimpleUploadedFile("laudo-da-placa-REG1A23.pdf", pdf_minimo(), content_type="application/pdf"))
        anexo = AnexoRegravacao.objects.get()
        nome = os.path.basename(anexo.arquivo.name)
        self.assertRegex(nome, r"^[0-9a-f]{32}\.pdf$")
        self.assertNotIn("REG1A23", anexo.arquivo.name.upper())
        for publica in (settings.STATICFILES_DIRS[0], settings.MEDIA_ROOT):
            self.assertFalse(str(anexo.arquivo.path).startswith(str(publica)))


class AcessoAosAnexosTest(BaseRegravacaoTest):
    def setUp(self):
        super().setUp()
        self.r = self.registro()
        self.anexar(self.r, Tipo.LAUDO_ECV)
        self.anexo = self.r.anexos.get()
        self.url = reverse("anexo_baixar", args=[self.anexo.pk, "arquivo"])

    def test_exige_login(self):
        self.assertRedirects(self.client.get(self.url), f"{reverse('login')}?next={self.url}")

    def test_exige_permissao(self):
        self.client.force_login(get_user_model().objects.create_user("semperm", password="x"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_funcionario_nao_baixa_com_o_modulo_oculto(self):
        self.client.force_login(self.func)
        from django.test import override_settings
        from contas.permissoes import ACESSO_POR_PERFIL
        with override_settings(ACESSO_POR_PERFIL=ACESSO_POR_PERFIL):
            self.func._modulos_acesso = None
            self.client.force_login(get_user_model().objects.get(pk=self.func.pk))
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_baixa_sem_cache_publico(self):
        self.client.force_login(self.admin)
        resposta = self.client.get(self.url)
        self.assertEqual((resposta.status_code, resposta["Content-Type"]), (200, "application/pdf"))
        self.assertIn("no-store", resposta["Cache-Control"])
        self.assertEqual(resposta["X-Content-Type-Options"], "nosniff")
        self.assertTrue(b"".join(resposta.streaming_content).startswith(b"%PDF-"))

    def test_tamanho_invalido_e_inexistente(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(f"/regravacoes/anexo/{self.anexo.pk}/enorme/").status_code, 404)
        self.assertEqual(self.client.get(reverse("anexo_baixar", args=[self.anexo.pk, "mini"])).status_code, 404)  # PDF não tem miniatura
        self.assertEqual(self.client.get(reverse("anexo_baixar", args=[99999, "arquivo"])).status_code, 404)

    def test_pasta_dos_anexos_nao_e_servida_pelo_site(self):
        self.client.force_login(self.admin)
        for caminho in (f"/media/{self.anexo.arquivo.name}", f"/static/{self.anexo.arquivo.name}"):
            self.assertEqual(self.client.get(caminho).status_code, 404, caminho)
