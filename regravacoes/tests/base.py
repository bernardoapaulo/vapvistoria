import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from atendimentos.tests.base import BaseAtendimentoTest
from regravacoes import regras
from regravacoes.models import AnexoRegravacao, ConfiguracaoEmpresa, Parceiro, RegistroRegravacao, Tecnico
from servicos.models import TipoServico
from vip_preparacao.tests.base import jpeg

Tipo = AnexoRegravacao.Tipo


def pdf_minimo(texto="Anexo de teste"):
    """Um PDF válido e pequeno (gerado pelo ReportLab)."""
    from reportlab.pdfgen import canvas
    saida = BytesIO()
    c = canvas.Canvas(saida)
    c.drawString(72, 720, texto)
    c.save()
    return saida.getvalue()


def arquivo_pdf(nome="autorizacao.pdf", texto="Anexo de teste"):
    return SimpleUploadedFile(nome, pdf_minimo(texto), content_type="application/pdf")


def arquivo_jpeg(nome="documento.jpg", **kw):
    return SimpleUploadedFile(nome, jpeg(**kw), content_type="image/jpeg")


def texto_do_pdf(conteudo):
    return " ".join(p.extract_text() for p in PdfReader(BytesIO(bytes(conteudo))).pages)


class BaseRegravacaoTest(BaseAtendimentoTest):
    """Administrador e Funcionário, empresa configurada (dados inventados), serviços de Regravação e um técnico."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cat = TipoServico.Categoria.REGRAVACAO
        cls.srv_motor = TipoServico.objects.create(nome="Regravação de motor", categoria=cat, valor_padrao="450.00")
        cls.srv_chassi = TipoServico.objects.create(nome="Regravação de chassi", categoria=cat, valor_padrao="400.00")
        cls.srv_ambos = TipoServico.objects.create(nome="Regravação de motor e chassi", categoria=cat, valor_padrao="800.00")
        cls.empresa = ConfiguracaoEmpresa.obter()
        cls.empresa.razao_social, cls.empresa.cnpj = "Empresa de Teste Ltda - ME", "11.222.333/0001-81"
        cls.empresa.endereco, cls.empresa.telefones, cls.empresa.cidade = "Rua de Teste, 1 - Centro", "(00) 0000-0000", "Cidade Teste"
        cls.empresa.rodape, cls.empresa.responsavel_recibo_nome, cls.empresa.responsavel_recibo_funcao = "Rodapé de teste", "Responsável Teste", "Sócio"
        cls.empresa.servico_motor, cls.empresa.servico_chassi, cls.empresa.servico_motor_chassi = cls.srv_motor, cls.srv_chassi, cls.srv_ambos
        cls.empresa.save()
        cls.tecnico = Tecnico.objects.create(nome="Técnico de Teste", funcao="Técnico responsável", credencial="REG-9")
        cls.parceiro = Parceiro.objects.create(nome="Parceiro de Teste", telefone="1")

    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="reg_anexos_")
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)
        for nome in ("arquivo", "miniatura"):
            armazenamento = AnexoRegravacao._meta.get_field(nome).storage
            for atributo in ("base_location", "location"):
                armazenamento.__dict__[atributo] = self.pasta
            self.addCleanup(lambda a=armazenamento: [a.__dict__.pop(k, None) for k in ("base_location", "location")])

    # ---------- atalhos ----------
    def registro(self, **extra):
        dados = dict(cliente=self.cliente, placa="REG1A23", marca="Fiat", modelo="Uno Teste", ano_modelo="2011/2012",
                     cor="branco", chassi="9BD00000000000001", numero_motor="MTR100001", proprietario="Fulano de Teste",
                     servico_motor=False, servico_chassi=True, valor=Decimal("400.00"),
                     criado_por=self.admin, alterado_por=self.admin)
        dados.update(extra)
        return RegistroRegravacao.objects.create(**dados)

    def anexar(self, r, *tipos):
        from regravacoes import anexos
        for tipo in tipos:
            regras.salvar_anexos(r, {tipo: anexos.processar(arquivo_pdf())}, set(), self.admin)

    def completa(self, **extra):
        """Concluída e com a autorização do serviço anexada (pronta para a Declaração)."""
        r = self.registro(data_agendada=self.dias(-3), data_concluida=self.dias(-1), tecnico=self.tecnico, **extra)
        self.anexar(r, *r.anexos_exigidos)
        return RegistroRegravacao.objects.get(pk=r.pk)

    def dados_form(self, **extra):
        dados = {
            "parceiro": "", "cliente": self.cliente.pk, "placa": "reg-1a23", "marca": "Fiat", "modelo": "Uno Teste",
            "ano_modelo": "2011/2012", "cor": "branco", "cor_outra": "", "chassi": "", "numero_motor": "",
            "proprietario": "", "servico_chassi": "on", "data_agendada": "", "data_concluida": "", "valor": "400.00",
            "recebimento_situacao": "pendente", "forma_pagamento": "", "data_recebimento": "", "tecnico": "", "observacao": "",
        }
        dados.update(extra)
        return {k: v for k, v in dados.items() if v is not None}

    def criar_pelo_form(self, usuario=None, **extra):
        self.client.force_login(usuario or self.admin)
        return self.client.post(reverse("regravacao_novo"), self.dados_form(**extra))

    @staticmethod
    def dias(n):
        return timezone.localdate() + timedelta(days=n)
