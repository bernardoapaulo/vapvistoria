import os
from io import BytesIO
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from vip_preparacao import fotos, regras
from vip_preparacao.models import FotoVip, RegistroVip

from .base import BaseVipTest, arquivo, jpeg


def exif_com_gps_e_orientacao(orientacao=1):
    exif = Image.Exif()
    exif[0x0112] = orientacao                      # orientação
    exif[0x010F] = "Fabricante Secreto"            # marca da câmera
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "S", (23.0, 33.0, 0.0), "W", (46.0, 38.0, 0.0)   # localização
    return exif


class ProcessamentoDasFotosTest(BaseVipTest):
    def test_aceita_jpeg_png_e_webp(self):
        for formato in ("JPEG", "PNG", "WEBP"):
            grande, mini, tamanho = fotos.processar(SimpleUploadedFile("f", jpeg(formato=formato)))
            self.assertEqual(Image.open(BytesIO(grande)).format, "JPEG", formato)   # sempre regravada como JPEG
            self.assertEqual(tamanho, (200, 100))

    def test_aceita_heic_do_iphone(self):
        import pillow_heif
        pillow_heif.register_heif_opener()
        saida = BytesIO()
        try:
            Image.new("RGB", (160, 120), (10, 120, 200)).save(saida, "HEIF")
        except Exception as e:  # pragma: no cover - sem codificador HEIF neste ambiente
            self.skipTest(f"sem codificador HEIF: {e}")
        grande, mini, tamanho = fotos.processar(SimpleUploadedFile("IMG_0001.HEIC", saida.getvalue()))
        self.assertEqual(Image.open(BytesIO(grande)).format, "JPEG")
        self.assertEqual(tamanho, (160, 120))

    def test_rejeita_arquivo_que_nao_e_imagem_mesmo_com_extensao_de_foto(self):
        for conteudo in (b"isto e um texto", b"%PDF-1.4 fake", b"\x89PNG\r\n\x1a\n" + b"lixo" * 10, b""):
            with self.assertRaises(ValidationError, msg=conteudo[:10]) as erro:
                fotos.processar(SimpleUploadedFile("foto.jpg", conteudo, content_type="image/jpeg"))
            self.assertIn("não é uma imagem válida", erro.exception.messages[0])

    def test_rejeita_foto_grande_demais(self):
        with mock.patch.dict(os.environ, {"VIP_FOTO_MAX_MB": "0.0001"}):     # ~100 bytes
            with self.assertRaises(ValidationError) as erro:
                fotos.processar(SimpleUploadedFile("f.jpg", jpeg(400, 300)))
        self.assertIn("Foto muito grande", erro.exception.messages[0])

    def test_limite_padrao_e_10_mb_e_configuravel(self):
        self.assertEqual(fotos.limite_bytes(), 10 * 1024 * 1024)
        with mock.patch.dict(os.environ, {"VIP_FOTO_MAX_MB": "3"}):
            self.assertEqual(fotos.limite_bytes(), 3 * 1024 * 1024)

    def test_reduz_para_no_maximo_1920_e_gera_miniatura(self):
        grande, mini, tamanho = fotos.processar(SimpleUploadedFile("f.jpg", jpeg(4000, 3000)))
        self.assertEqual(tamanho, (1920, 1440))
        self.assertEqual(Image.open(BytesIO(grande)).size, (1920, 1440))
        self.assertEqual(max(Image.open(BytesIO(mini)).size), fotos.LADO_MINIATURA)

    def test_nao_aumenta_foto_pequena(self):
        _, _, tamanho = fotos.processar(SimpleUploadedFile("f.jpg", jpeg(300, 200)))
        self.assertEqual(tamanho, (300, 200))

    def test_remove_exif_inclusive_gps(self):
        original = jpeg(exif=exif_com_gps_e_orientacao())
        self.assertIn(0x8825, Image.open(BytesIO(original)).getexif())             # a entrada TEM GPS
        grande, mini, _ = fotos.processar(SimpleUploadedFile("f.jpg", original))
        for saida in (grande, mini):
            imagem = Image.open(BytesIO(saida))
            self.assertEqual(dict(imagem.getexif()), {})
            self.assertNotIn(b"Fabricante Secreto", saida)
            self.assertNotIn(b"Exif", saida[:64])

    def test_corrige_a_orientacao_antes_de_descartar_o_exif(self):
        # 200x100 marcada como "girar 90°" (orientação 6) deve virar 100x200
        original = jpeg(200, 100, exif=exif_com_gps_e_orientacao(orientacao=6))
        _, _, tamanho = fotos.processar(SimpleUploadedFile("f.jpg", original))
        self.assertEqual(tamanho, (100, 200))


class FotosNoRegistroTest(BaseVipTest):
    def _post(self, registro, usuario=None, **arquivos):
        self.client.force_login(usuario or self.admin)
        dados = self.dados_form(placa=registro.placa, **arquivos)
        return self.client.post(reverse("vip_editar", args=[registro.pk]), dados)

    def test_envia_fotos_na_criacao_pelo_formulario(self):
        self.client.force_login(self.admin)
        dados = self.dados_form(foto_entrada_placa=arquivo("a.jpg"), foto_entrada_frente=arquivo("b.png", jpeg(formato="PNG"), "image/png"))
        resposta = self.client.post(reverse("vip_novo"), dados)
        self.assertEqual(resposta.status_code, 302)
        r = FotoVip.objects.first().registro
        self.assertEqual(set(r.fotos.values_list("momento", "posicao")), {("entrada", "placa"), ("entrada", "frente")})
        self.assertTrue(r.historico.filter(tipo="fotos").exists())

    def test_foto_invalida_mostra_erro_em_portugues_e_nao_salva_nada(self):
        self.client.force_login(self.admin)
        dados = self.dados_form(foto_entrada_placa=SimpleUploadedFile("x.jpg", b"nao sou imagem", content_type="image/jpeg"))
        resposta = self.client.post(reverse("vip_novo"), dados)
        self.assertContains(resposta, "não é uma imagem válida")
        self.assertEqual((FotoVip.objects.count(), RegistroVip.objects.count()), (0, 0))

    def test_trocar_foto_apaga_a_antiga_do_armazenamento(self):
        r = self.registro()
        with self.captureOnCommitCallbacks(execute=True):
            self._post(r, foto_entrada_placa=arquivo("a.jpg", jpeg(cor=(1, 2, 3))))
        antiga = FotoVip.objects.get()
        caminho_antigo = antiga.imagem.path
        self.assertTrue(os.path.exists(caminho_antigo))
        with self.captureOnCommitCallbacks(execute=True):
            self._post(r, foto_entrada_placa=arquivo("b.jpg", jpeg(cor=(9, 9, 9))))
        self.assertEqual(FotoVip.objects.count(), 1)                         # uma foto por posição
        self.assertFalse(os.path.exists(caminho_antigo))
        self.assertTrue(os.path.exists(FotoVip.objects.get().imagem.path))

    def test_remover_foto(self):
        r = self.registro()
        with self.captureOnCommitCallbacks(execute=True):
            self._post(r, foto_entrada_placa=arquivo())
        with self.captureOnCommitCallbacks(execute=True):
            self._post(r, remover_entrada_placa="on")
        self.assertEqual(FotoVip.objects.count(), 0)

    def test_nome_do_arquivo_nao_e_adivinhavel_e_fica_fora_de_pastas_publicas(self):
        r = self.registro()
        self._post(r, foto_entrada_placa=arquivo("minha-placa-ABC1234.jpg"))
        foto = FotoVip.objects.get()
        nome = os.path.basename(foto.imagem.name)
        self.assertRegex(nome, r"^[0-9a-f]{32}\.jpg$")
        self.assertNotIn("placa", nome.lower())
        for pasta_publica in (settings.STATICFILES_DIRS[0], settings.MEDIA_ROOT):
            self.assertFalse(str(foto.imagem.path).startswith(str(pasta_publica)))

    def test_fotos_de_saida_em_registro_aberto_tambem_funcionam(self):
        r = self.registro()
        self._post(r, foto_saida_frente=arquivo())
        self.assertEqual(FotoVip.objects.get().momento, "saida")


class AcessoAsFotosTest(BaseVipTest):
    def setUp(self):
        super().setUp()
        self.r = self.registro()
        regras.salvar_fotos(self.r, {("entrada", "placa"): (jpeg(), jpeg(40, 30))}, set(), self.admin)
        self.foto = self.r.fotos.get()
        self.url = reverse("vip_foto", args=[self.foto.pk, "grande"])

    def test_exige_login(self):
        resposta = self.client.get(self.url)
        self.assertRedirects(resposta, f"{reverse('login')}?next={self.url}")

    def test_exige_permissao(self):
        sem_permissao = get_user_model().objects.create_user("semperm", password="x")
        self.client.force_login(sem_permissao)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_com_permissao_entrega_a_imagem_sem_cache_publico(self):
        for usuario in (self.admin, self.func):
            self.client.force_login(usuario)
            resposta = self.client.get(self.url)
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual(resposta["Content-Type"], "image/jpeg")
            self.assertIn("private", resposta["Cache-Control"])
            self.assertEqual(resposta["X-Content-Type-Options"], "nosniff")
            self.assertEqual(Image.open(BytesIO(b"".join(resposta.streaming_content))).format, "JPEG")

    def test_miniatura_e_tamanho_invalido(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("vip_foto", args=[self.foto.pk, "mini"])).status_code, 200)
        self.assertEqual(self.client.get(f"/vip/foto/{self.foto.pk}/enorme/").status_code, 404)
        self.assertEqual(self.client.get(reverse("vip_foto", args=[99999, "mini"])).status_code, 404)

    def test_a_pasta_das_fotos_nao_e_servida_pelo_site(self):
        self.client.force_login(self.admin)
        for caminho in (f"/media/{self.foto.imagem.name}", f"/static/{self.foto.imagem.name}", f"/arquivos_privados/{self.foto.imagem.name}"):
            self.assertEqual(self.client.get(caminho).status_code, 404, caminho)

    def test_detalhe_usa_a_view_protegida_e_miniaturas(self):
        self.client.force_login(self.admin)
        html = self.client.get(self.r.get_absolute_url()).content.decode()
        self.assertIn(reverse("vip_foto", args=[self.foto.pk, "mini"]), html)
        self.assertIn(reverse("vip_foto", args=[self.foto.pk, "grande"]), html)    # só ao clicar (lightbox)
        self.assertNotRegex(html, r"/(media|static)/vip/")
        self.assertIn('alt="Entrada: Placa"', html)
