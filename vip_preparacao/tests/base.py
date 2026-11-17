import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from atendimentos.tests.base import BaseAtendimentoTest
from servicos.models import TipoServico
from vip_preparacao.models import FotoVip, RegistroVip


def jpeg(largura=200, altura=100, cor=(200, 30, 30), exif=None, formato="JPEG"):
    """Bytes de uma imagem de teste (JPEG por padrão); `exif` é um objeto Image.Exif."""
    imagem = Image.new("RGB", (largura, altura), cor)
    saida = BytesIO()
    imagem.save(saida, formato, **({"exif": exif} if exif is not None else {}))
    return saida.getvalue()


def arquivo(nome="foto.jpg", dados=None, tipo="image/jpeg"):
    return SimpleUploadedFile(nome, dados if dados is not None else jpeg(), content_type=tipo)


class BaseVipTest(BaseAtendimentoTest):
    """Dois perfis, um cliente e um serviço de VIP; as fotos vão para uma pasta temporária."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.vip = TipoServico.objects.create(nome="VIP completo", categoria=TipoServico.Categoria.LIMPEZA, valor_padrao="150.00")
        cls.preparacao = TipoServico.objects.create(
            nome="Preparação", categoria=TipoServico.Categoria.REPAROS, valor_padrao="300.00")

    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="vip_fotos_")
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)
        for nome in ("imagem", "miniatura"):
            armazenamento = FotoVip._meta.get_field(nome).storage
            for atributo in ("base_location", "location"):
                armazenamento.__dict__[atributo] = self.pasta
            self.addCleanup(lambda a=armazenamento: [a.__dict__.pop(k, None) for k in ("base_location", "location")])

    # ---------- atalhos ----------
    def registro(self, **extra):
        dados = dict(
            cliente=self.cliente, placa="NOV1A23", marca="Fiat", modelo="Argo", versao="Drive", cor="branco", ano=2021,
            servico=self.vip, data_preparacao=timezone.localdate(), valor=Decimal("150.00"),
            criado_por=self.admin, alterado_por=self.admin)
        dados.update(extra)
        return RegistroVip.objects.create(**dados)

    def dados_form(self, **extra):
        dados = {
            "cliente": self.cliente.pk, "placa": "abc-1d23", "marca": "Fiat", "modelo": "Argo", "versao": "Drive 1.3",
            "cor": "branco", "cor_outra": "", "ano": "2021", "chassi": "", "servico": self.vip.pk,
            "data_preparacao": date.today().isoformat(), "data_vip": "", "data_devolucao": "", "valor": "",
            "previsao_pagamento": "", "nota_fiscal": "", "observacao": "",
        }
        dados.update(extra)
        return dados

    def criar_pelo_form(self, usuario=None, **extra):
        self.client.force_login(usuario or self.admin)
        return self.client.post(reverse("vip_novo"), self.dados_form(**extra))

    def concluir(self, registro, usuario=None, **extra):
        self.client.force_login(usuario or self.admin)
        dados = {"valor": str(registro.valor), "forma": "pix", "data": date.today().isoformat()}
        dados.update(extra)
        return self.client.post(reverse("vip_concluir", args=[registro.pk]), dados, follow=True)

    @staticmethod
    def dias(n):
        return timezone.localdate() + timedelta(days=n)
