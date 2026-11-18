"""
Módulo Regravações (só Administrador, por padrão): solicitações de regravação de motor e/ou chassi, com parceiro
indicador, cliente, veículo, técnico, anexos e a emissão em PDF da Declaração de Serviço e do Recibo de Pagamento.

Quando o registro está CONCLUÍDO e RECEBIDO, `regras.lancar` cria o Atendimento concluído e pago e o Recebimento no
Financeiro (mesmo padrão do Vip/Preparação). Os PDFs emitidos ficam guardados no banco (cópia fiel, nunca recalculada).
"""
import re
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import Atendimento
from cadastros.models import Cliente
from cadastros.validators import normalizar_placa, validar_placa
from financeiro.models import Auditavel, FormaPagamento
from servicos.models import TipoServico
from vip_preparacao.armazenamento import armazenamento_fotos
from vip_preparacao.models import Cor, validar_chassi

ZERO = Decimal("0.00")
ANO_MODELO = re.compile(r"^(\d{4})/(\d{4})$")


def validar_ano_modelo(valor):
    """AAAA/AAAA (ex.: 2011/2012): faixa razoável e o segundo ano não pode ser menor que o primeiro."""
    achado = ANO_MODELO.match((valor or "").strip())
    if not achado:
        raise ValidationError("Informe o ano no formato AAAA/AAAA, por exemplo 2011/2012.")
    fabricacao, modelo = int(achado.group(1)), int(achado.group(2))
    limite = date.today().year + 1
    if not (1950 <= fabricacao <= limite and 1950 <= modelo <= limite):
        raise ValidationError(f"Os anos devem estar entre 1950 e {limite}.")
    if modelo < fabricacao:
        raise ValidationError("O ano do modelo não pode ser menor que o ano de fabricação.")


# ---------- Cadastros de apoio ----------
class Parceiro(models.Model):
    """Quem indicou o cliente (despachante, loja, oficina...). Sem comissão nem pagamento: fora do escopo."""
    nome = models.CharField("nome", max_length=150)
    telefone = models.CharField("telefone / WhatsApp", max_length=20, blank=True)
    empresa_profissao = models.CharField("empresa ou profissão", max_length=120, blank=True)
    observacoes = models.TextField("observações", blank=True)
    ativo = models.BooleanField("ativo", default=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "parceiro indicador"
        verbose_name_plural = "parceiros indicadores"
        ordering = ["nome"]
        permissions = [("ver_faturamento_parceiro", "Pode ver o total faturado nas indicações do parceiro")]

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("parceiro_detalhe", args=[self.pk])


class Tecnico(models.Model):
    """Responsável pelo serviço (aparece nos documentos). Desativar não altera documentos já emitidos."""
    nome = models.CharField("nome completo", max_length=150)
    funcao = models.CharField("função / cargo", max_length=100, blank=True)
    credencial = models.CharField("credencial / registro", max_length=60, blank=True)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "técnico responsável"
        verbose_name_plural = "técnicos responsáveis"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("tecnico_editar", args=[self.pk])


class ConfiguracaoEmpresa(models.Model):
    """Dados da empresa usados nos PDFs (uma linha só). Nada disto fica escrito no código."""
    razao_social = models.CharField("razão social", max_length=150, blank=True)
    cnpj = models.CharField("CNPJ", max_length=18, blank=True)
    endereco = models.CharField("endereço", max_length=255, blank=True)
    telefones = models.CharField("telefones", max_length=120, blank=True)
    cidade = models.CharField("cidade", max_length=80, blank=True)
    rodape = models.CharField("texto do rodapé", max_length=200, blank=True)
    logo = models.BinaryField("logo", null=True, blank=True, editable=False)
    logo_tipo = models.CharField(max_length=20, blank=True, editable=False)
    responsavel_recibo_nome = models.CharField("responsável que assina o recibo", max_length=150, blank=True)
    responsavel_recibo_funcao = models.CharField("função do responsável", max_length=100, blank=True)
    servico_motor = models.ForeignKey(
        TipoServico, verbose_name="serviço: regravação de motor", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    servico_chassi = models.ForeignKey(
        TipoServico, verbose_name="serviço: regravação de chassi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    servico_motor_chassi = models.ForeignKey(
        TipoServico, verbose_name="serviço: regravação de motor e chassi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "configuração da empresa"
        verbose_name_plural = "configuração da empresa"

    def __str__(self):
        return self.razao_social or "Configuração da empresa"

    @classmethod
    def obter(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def faltando_para_documentos(self):
        faltam = []
        for campo, rotulo in (("razao_social", "razão social"), ("cnpj", "CNPJ"), ("endereco", "endereço"),
                              ("telefones", "telefones"), ("cidade", "cidade")):
            if not getattr(self, campo):
                faltam.append(rotulo)
        return faltam

    def servico_para(self, motor, chassi):
        if motor and chassi:
            return self.servico_motor_chassi
        return self.servico_motor if motor else self.servico_chassi if chassi else None


# ---------- Registro ----------
class RegistroRegravacao(Auditavel):
    class Situacao(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        RECEBIDO = "recebido", "Recebido"

    class Status(models.TextChoices):
        SOLICITADA = "solicitada", "Solicitada"
        AGENDADA = "agendada", "Agendada"
        CONCLUIDA = "concluida", "Concluída"
        CANCELADA = "cancelada", "Cancelada"

    parceiro = models.ForeignKey(
        Parceiro, verbose_name="parceiro indicador", null=True, blank=True, on_delete=models.PROTECT,
        related_name="registros")
    cliente = models.ForeignKey(
        Cliente, verbose_name="cliente indicado", on_delete=models.PROTECT, related_name="regravacoes")
    placa = models.CharField("placa", max_length=8, validators=[validar_placa])
    marca = models.CharField("marca", max_length=60, blank=True)
    modelo = models.CharField("modelo", max_length=80, blank=True)
    ano_modelo = models.CharField("ano/modelo", max_length=9, blank=True, validators=[validar_ano_modelo])
    cor = models.CharField("cor", max_length=15, choices=Cor.choices, blank=True)
    cor_outra = models.CharField("descrição da cor", max_length=30, blank=True)
    chassi = models.CharField("chassi", max_length=17, blank=True, validators=[validar_chassi])
    numero_motor = models.CharField("número do motor", max_length=40, blank=True)
    proprietario = models.CharField("proprietário do veículo", max_length=150, blank=True)
    proprietario_e_cliente = models.BooleanField("o proprietário é o próprio cliente", default=False)

    servico_motor = models.BooleanField("regravação de motor", default=False)
    servico_chassi = models.BooleanField("regravação de chassi", default=False)
    data_agendada = models.DateField("data agendada", null=True, blank=True)
    data_concluida = models.DateField("data do serviço concluído", null=True, blank=True)
    valor = models.DecimalField(
        "valor (R$)", max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO, "O valor não pode ser negativo.")])
    recebimento_situacao = models.CharField(
        "recebimento", max_length=10, choices=Situacao.choices, default=Situacao.PENDENTE)
    forma_pagamento = models.CharField("forma de pagamento", max_length=15, choices=FormaPagamento.choices, blank=True)
    data_recebimento = models.DateField("data do recebimento", null=True, blank=True)
    tecnico = models.ForeignKey(
        Tecnico, verbose_name="técnico responsável", null=True, blank=True, on_delete=models.PROTECT,
        related_name="registros")
    observacao = models.TextField("observação", blank=True)

    cancelada = models.BooleanField("cancelada", default=False)
    motivo_cancelamento = models.CharField("motivo do cancelamento", max_length=200, blank=True)
    # Atendimento (e, por ele, o Recebimento) gerado quando está concluída E recebida. Fica ligado mesmo se reaberta.
    atendimento = models.OneToOneField(
        Atendimento, verbose_name="atendimento gerado", null=True, blank=True, editable=False,
        on_delete=models.PROTECT, related_name="registro_regravacao")
    lancado_em = models.DateTimeField("lançado no Financeiro em", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "regravação"
        verbose_name_plural = "regravações"
        ordering = ["-criado_em", "-id"]
        indexes = [models.Index(fields=["placa"]), models.Index(fields=["data_concluida"])]
        permissions = [
            ("alterar_valor_regravacao", "Pode alterar o valor da regravação"),
            ("concluir_regravacao", "Pode concluir e registrar o recebimento da regravação"),
            ("reabrir_regravacao", "Pode reabrir regravação lançada no Financeiro"),
            ("emitir_documento_regravacao", "Pode emitir Declaração e Recibo em PDF"),
            ("editar_lancada_regravacao", "Pode editar regravação já concluída e recebida"),
        ]

    def __str__(self):
        return f"Regravação #{self.pk} - {self.placa}"

    def get_absolute_url(self):
        return reverse("regravacao_detalhe", args=[self.pk])

    # ---------- Propriedades de apoio ----------
    @property
    def lancado(self):
        return self.lancado_em is not None

    @property
    def status(self):
        """Calculado: Cancelada > Concluída (data e técnico) > Agendada (data agendada) > Solicitada."""
        if self.cancelada:
            return self.Status.CANCELADA
        if self.data_concluida and self.tecnico_id:
            return self.Status.CONCLUIDA
        if self.data_agendada:
            return self.Status.AGENDADA
        return self.Status.SOLICITADA

    @property
    def status_texto(self):
        return self.Status(self.status).label

    @property
    def servicos_texto(self):
        if self.servico_motor and self.servico_chassi:
            return "Motor e chassi"
        return "Motor" if self.servico_motor else "Chassi" if self.servico_chassi else "—"

    @property
    def cor_texto(self):
        if self.cor == Cor.OUTRA:
            return self.cor_outra or "Outra"
        return self.get_cor_display() if self.cor else ""

    @property
    def veiculo_texto(self):
        return " ".join(p for p in (self.marca, self.modelo) if p)

    @property
    def nome_proprietario(self):
        return self.cliente.nome if self.proprietario_e_cliente else self.proprietario

    @property
    def anexos_exigidos(self):
        exigidos = []
        if self.servico_motor:
            exigidos.append(AnexoRegravacao.Tipo.AUTORIZACAO_MOTOR)
        if self.servico_chassi:
            exigidos.append(AnexoRegravacao.Tipo.AUTORIZACAO_CHASSI)
        return exigidos

    @property
    def anexos_pendentes(self):
        """Autorizações exigidas ainda não anexadas (usa prefetch_related('anexos') nas listagens)."""
        enviados = {a.tipo for a in self.anexos.all()}
        return [t for t in self.anexos_exigidos if t not in enviados]

    @property
    def total_documentos_pendentes(self):
        return len(self.anexos_pendentes)

    # ---------- Regras ----------
    def clean(self):
        erros = {}
        self.placa = normalizar_placa(self.placa)
        self.chassi = (self.chassi or "").strip().upper()
        if not (self.servico_motor or self.servico_chassi):
            erros["servico_motor"] = "Marque pelo menos um serviço: regravação de motor e/ou de chassi."
        if self.cor == Cor.OUTRA and not (self.cor_outra or "").strip():
            erros["cor_outra"] = "Descreva a cor."
        hoje = timezone.localdate()
        if self.data_agendada and self.data_concluida and self.data_concluida < self.data_agendada:
            erros["data_concluida"] = "A data do serviço concluído não pode ser anterior à data agendada."
        if self.data_concluida and self.data_concluida > hoje:
            erros["data_concluida"] = "A data do serviço concluído não pode ser no futuro."
        if self.recebimento_situacao == self.Situacao.RECEBIDO:
            if not self.forma_pagamento:
                erros["forma_pagamento"] = "Informe a forma de pagamento do recebimento."
            if not self.data_recebimento:
                erros["data_recebimento"] = "Informe a data do recebimento."
            elif self.data_recebimento > hoje:
                erros["data_recebimento"] = "A data do recebimento não pode ser no futuro."
        if self.proprietario_e_cliente:
            self.proprietario = ""
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        self.placa = normalizar_placa(self.placa)
        self.chassi = (self.chassi or "").strip().upper()
        super().save(*args, **kwargs)


class AnexoRegravacao(models.Model):
    class Tipo(models.TextChoices):
        AUTORIZACAO_MOTOR = "autorizacao_motor", "Autorização de Motor"
        AUTORIZACAO_CHASSI = "autorizacao_chassi", "Autorização de Chassi"
        DOCUMENTO_VEICULO = "documento_veiculo", "Documento do Veículo"
        LAUDO_ECV = "laudo_ecv", "Laudo de Vistoria ECV"
        RECIBO_EXTERNO = "recibo_externo", "Recibo de Pagamento (anexado)"

    registro = models.ForeignKey(RegistroRegravacao, on_delete=models.CASCADE, related_name="anexos")
    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices)
    # Nomes aleatórios, fora de qualquer pasta pública; só a view protegida entrega os arquivos (LGPD).
    arquivo = models.FileField("arquivo", upload_to="regravacoes/%Y/%m/", storage=armazenamento_fotos)
    miniatura = models.FileField("miniatura", upload_to="regravacoes/mini/%Y/%m/", storage=armazenamento_fotos, blank=True)
    nome_original = models.CharField("nome do arquivo enviado", max_length=150, blank=True)
    content_type = models.CharField(max_length=30)
    tamanho = models.PositiveIntegerField(default=0)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    enviado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "anexo de regravação"
        verbose_name_plural = "anexos de regravação"
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["registro", "tipo"], name="uniq_anexo_regravacao_tipo")]

    def __str__(self):
        return f"{self.get_tipo_display()} ({self.registro})"

    @property
    def e_imagem(self):
        return self.content_type.startswith("image/")


# ---------- Documentos emitidos ----------
class SequenciaDocumento(models.Model):
    """Contador por tipo e ano (trava de linha ao numerar: nunca repete, nem com acessos simultâneos)."""
    tipo = models.CharField(max_length=12)
    ano = models.PositiveSmallIntegerField()
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tipo", "ano"], name="uniq_sequencia_documento")]


class DocumentoEmitido(models.Model):
    class Tipo(models.TextChoices):
        DECLARACAO = "declaracao", "Declaração de Serviço"
        RECIBO = "recibo", "Recibo de Pagamento"

    registro = models.ForeignKey(RegistroRegravacao, on_delete=models.PROTECT, related_name="documentos")
    tipo = models.CharField("tipo", max_length=12, choices=Tipo.choices)
    ano = models.PositiveSmallIntegerField("ano")
    sequencia = models.PositiveIntegerField("número sequencial")
    pdf = models.BinaryField("PDF emitido", editable=False)           # cópia fiel: nunca é recalculada
    hash_dados = models.CharField(max_length=64, editable=False)       # dados usados: detecta se mudaram depois
    emitido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    emitido_em = models.DateTimeField(default=timezone.now)
    substitui = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="substituido_por")

    class Meta:
        verbose_name = "documento emitido"
        verbose_name_plural = "documentos emitidos"
        ordering = ["-emitido_em", "-id"]
        constraints = [models.UniqueConstraint(fields=["tipo", "ano", "sequencia"], name="uniq_numero_documento")]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.numero}"

    @property
    def numero(self):
        return f"{self.ano}/{self.sequencia:04d}"

    @property
    def substituido(self):
        return self.substituido_por.exists()

    def get_absolute_url(self):
        return reverse("documento_baixar", args=[self.pk])


class HistoricoRegravacao(models.Model):
    class Tipo(models.TextChoices):
        CRIACAO = "criacao", "Criação"
        EDICAO = "edicao", "Edição"
        STATUS = "status", "Status"
        RECEBIMENTO = "recebimento", "Recebimento"
        ANEXO = "anexo", "Anexo"
        DOCUMENTO = "documento", "Documento"
        FINANCEIRO = "financeiro", "Financeiro"
        REABERTURA = "reabertura", "Reabertura"

    registro = models.ForeignKey(RegistroRegravacao, on_delete=models.CASCADE, related_name="historico")
    tipo = models.CharField("tipo", max_length=12, choices=Tipo.choices)
    valor_anterior = models.CharField("de", max_length=300, blank=True)
    valor_novo = models.CharField("para", max_length=300)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuário", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    data_hora = models.DateTimeField("data e hora", default=timezone.now)

    class Meta:
        verbose_name = "histórico de regravação"
        verbose_name_plural = "históricos de regravação"
        ordering = ["data_hora", "id"]
