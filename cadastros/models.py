from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse

from .validators import (
    CaminhoUpload,
    formatar_cep,
    formatar_cpf,
    mascarar_cpf_cnpj,
    normalizar_placa,
    validar_cep,
    validar_cpf,
    validar_cpf_cnpj,
    validar_documento,
    validar_foto,
    validar_placa,
)


class Cliente(models.Model):
    nome = models.CharField("nome", max_length=150)
    cpf_cnpj = models.CharField(
        "CPF/CNPJ", max_length=18, blank=True, validators=[validar_cpf_cnpj],
        help_text="Opcional. Pode digitar com ou sem pontos e traços.",
    )
    telefone = models.CharField("telefone", max_length=20)
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True)
    email = models.EmailField("e-mail", blank=True)
    observacoes = models.TextField("observações", blank=True)
    data_cadastro = models.DateField("data de cadastro", default=date.today)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("cliente_detalhe", args=[self.pk])

    @property
    def cpf_cnpj_mascarado(self):
        return mascarar_cpf_cnpj(self.cpf_cnpj)


class Aluno(models.Model):
    class Sexo(models.TextChoices):
        FEMININO = "F", "Feminino"
        MASCULINO = "M", "Masculino"

    # Campos dos documentos enviados: (nome do campo, rótulo exibido)
    DOCUMENTOS = [
        ("foto", "Foto do aluno"),
        ("antecedentes_criminais", "Antecedentes criminais"),
        ("certidao_negativa", "Certidão negativa"),
        ("conclusao_ensino_medio", "Conclusão do ensino médio"),
        ("documento_identificacao", "CPF, RG ou CNH"),
    ]

    nome = models.CharField("nome", max_length=150)
    # Obrigatório em cadastros novos; nulo apenas para alunos antigos (anteriores a esta versão).
    cpf = models.CharField(
        "CPF", max_length=14, unique=True, null=True, validators=[validar_cpf],
        error_messages={"unique": "Já existe um aluno cadastrado com este CPF."},
        help_text="Pode digitar com ou sem pontos e traço.",
    )
    email = models.EmailField("e-mail", blank=True)
    data_nascimento = models.DateField("data de nascimento", null=True)
    sexo = models.CharField("sexo", max_length=1, choices=Sexo.choices, default="")
    celular = models.CharField("celular", max_length=20)
    endereco = models.CharField("endereço", max_length=255, default="")
    cep = models.CharField("CEP", max_length=9, default="", validators=[validar_cep])
    observacoes = models.TextField("observações", blank=True)
    data_cadastro = models.DateField("data de cadastro", default=date.today)
    cliente = models.ForeignKey(
        Cliente, verbose_name="cliente vinculado", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="alunos",
        help_text="Opcional. Use quando o aluno também é cliente da empresa.",
    )

    # Documentos (PDF, JPG ou PNG, até 5 MB). Opcionais: podem ser anexados depois.
    foto = models.FileField(
        "foto do aluno", upload_to=CaminhoUpload("fotos"), blank=True, validators=[validar_foto],
        help_text="JPG ou PNG, até 5 MB.",
    )
    antecedentes_criminais = models.FileField(
        "antecedentes criminais", upload_to=CaminhoUpload("antecedentes"), blank=True,
        validators=[validar_documento], help_text="PDF, JPG ou PNG, até 5 MB.",
    )
    certidao_negativa = models.FileField(
        "certidão negativa", upload_to=CaminhoUpload("certidoes"), blank=True,
        validators=[validar_documento], help_text="PDF, JPG ou PNG, até 5 MB.",
    )
    conclusao_ensino_medio = models.FileField(
        "conclusão do ensino médio", upload_to=CaminhoUpload("ensino_medio"), blank=True,
        validators=[validar_documento], help_text="PDF, JPG ou PNG, até 5 MB.",
    )
    documento_identificacao = models.FileField(
        "CPF, RG ou CNH", upload_to=CaminhoUpload("identificacao"), blank=True,
        validators=[validar_documento], help_text="PDF, JPG ou PNG, até 5 MB.",
    )

    class Meta:
        verbose_name = "aluno"
        verbose_name_plural = "alunos"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("aluno_detalhe", args=[self.pk])

    @property
    def cpf_mascarado(self):
        return mascarar_cpf_cnpj(self.cpf) if self.cpf else ""

    @property
    def situacao_documentos(self):
        """Lista de (campo, rótulo, enviado?) para mostrar o que falta anexar."""
        return [(campo, rotulo, bool(getattr(self, campo))) for campo, rotulo in self.DOCUMENTOS]

    def clean(self):
        # Guarda CPF e CEP sempre formatados (evita duplicidade por máscara diferente).
        if self.cpf:
            self.cpf = formatar_cpf(self.cpf)
        if self.cep:
            self.cep = formatar_cep(self.cep)


@receiver(post_delete, sender=Aluno)
def apagar_documentos_do_aluno(sender, instance, **kwargs):
    """Ao excluir o aluno, remove também os arquivos (LGPD: não guardar o que não é mais necessário)."""
    for campo, _ in Aluno.DOCUMENTOS:
        arquivo = getattr(instance, campo)
        if arquivo:
            arquivo.delete(save=False)


class Veiculo(models.Model):
    placa = models.CharField(
        "placa", max_length=8, unique=True, validators=[validar_placa],
        error_messages={"unique": "Já existe um veículo cadastrado com esta placa."},
    )
    marca = models.CharField("marca", max_length=60)
    modelo = models.CharField("modelo", max_length=80)
    ano = models.PositiveSmallIntegerField(
        "ano",
        validators=[
            MinValueValidator(1950, "Informe um ano a partir de 1950."),
            MaxValueValidator(date.today().year + 1, "O ano não pode estar tão no futuro."),
        ],
    )
    cor = models.CharField("cor", max_length=30)
    chassi = models.CharField("chassi", max_length=17, blank=True)
    proprietario = models.ForeignKey(
        Cliente, verbose_name="proprietário", on_delete=models.PROTECT,
        related_name="veiculos",
    )
    observacoes = models.TextField("observações", blank=True)

    class Meta:
        verbose_name = "veículo"
        verbose_name_plural = "veículos"
        ordering = ["placa"]

    def __str__(self):
        return f"{self.placa} - {self.marca} {self.modelo}"

    def get_absolute_url(self):
        return reverse("veiculo_detalhe", args=[self.pk])

    def clean(self):
        # Guarda a placa sempre em maiúsculas e sem hífen/espaços.
        self.placa = normalizar_placa(self.placa)
        self.chassi = (self.chassi or "").strip().upper()
        if self.chassi and len(self.chassi) != 17:
            raise ValidationError({"chassi": "O chassi deve ter 17 caracteres."})

    def save(self, *args, **kwargs):
        self.placa = normalizar_placa(self.placa)
        super().save(*args, **kwargs)
