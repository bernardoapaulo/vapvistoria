"""
Modelos do Financeiro.

REGIMES (definições usadas em todo o módulo; ver também financeiro/services.py)
- Caixa: receita = dinheiro efetivamente recebido na DATA DO RECEBIMENTO; despesa = dinheiro
  efetivamente pago na DATA DO PAGAMENTO.
- Competência (só "a receber", "a pagar" e margem por serviço): o que foi vendido ou devido,
  independentemente de já ter sido pago.

Nada aqui é apagado em silêncio: recebimento nunca é excluído (só estornado) e toda alteração
importante é gravada em RegistroAuditoria.
"""
import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import Atendimento
from servicos.models import TipoServico

from .dinheiro import ZERO

VALOR_MINIMO = MinValueValidator(Decimal("0.01"), "O valor deve ser maior que zero.")


class FormaPagamento(models.TextChoices):
    DINHEIRO = "dinheiro", "Dinheiro"
    PIX = "pix", "Pix"
    DEBITO = "cartao_debito", "Cartão de débito"
    CREDITO = "cartao_credito", "Cartão de crédito"
    TRANSFERENCIA = "transferencia", "Transferência"


def armazenamento_privado():
    """Pasta FORA de static/media: o arquivo só sai pela view protegida (despesa_comprovante)."""
    return FileSystemStorage(location=settings.ARQUIVOS_PRIVADOS_ROOT)


def caminho_comprovante(instancia, nome_original):
    extensao = os.path.splitext(nome_original)[1].lower()
    return f"comprovantes/{uuid.uuid4().hex}{extensao}"  # nome aleatório: nunca expõe o original


class Auditavel(models.Model):
    """Quem criou, quem alterou por último e quando."""
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="criado por", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+", editable=False,
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    alterado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="alterado por", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+", editable=False,
    )
    alterado_em = models.DateTimeField("alterado em", auto_now=True)

    class Meta:
        abstract = True


# ---------- Recebimentos ----------
class RecebimentoQuerySet(models.QuerySet):
    def validos(self):
        """Dinheiro que realmente entrou (estornos ficam de fora)."""
        return self.filter(estornado_em__isnull=True)

    def estornados(self):
        return self.filter(estornado_em__isnull=False)

    def no_periodo(self, inicio, fim):
        return self.filter(data__gte=inicio, data__lte=fim)


class Recebimento(Auditavel):
    """Dinheiro recebido por um atendimento. Um atendimento pode ter vários (pagamento em partes)."""

    atendimento = models.ForeignKey(
        Atendimento, verbose_name="atendimento", on_delete=models.PROTECT, related_name="recebimentos",
    )
    valor = models.DecimalField("valor (R$)", max_digits=10, decimal_places=2, validators=[VALOR_MINIMO])
    data = models.DateField("data do recebimento", default=timezone.localdate)
    forma = models.CharField("forma de pagamento", max_length=15, choices=FormaPagamento.choices)
    observacao = models.CharField("observação", max_length=300, blank=True)

    # Estorno: o recebimento continua existindo (histórico), mas deixa de contar.
    estornado_em = models.DateTimeField("estornado em", null=True, blank=True, editable=False)
    estornado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="estornado por", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+", editable=False,
    )
    motivo_estorno = models.CharField("motivo do estorno", max_length=300, blank=True, editable=False)

    objects = RecebimentoQuerySet.as_manager()

    class Meta:
        verbose_name = "recebimento"
        verbose_name_plural = "recebimentos"
        ordering = ["-data", "-id"]
        indexes = [models.Index(fields=["data"])]
        constraints = [models.CheckConstraint(condition=Q(valor__gt=0), name="recebimento_valor_positivo")]
        permissions = [
            ("ver_financeiro", "Pode acessar o módulo Financeiro"),
            ("estornar_recebimento", "Pode estornar recebimentos"),
        ]

    def __str__(self):
        return f"Recebimento #{self.pk} - {self.atendimento}"

    def get_absolute_url(self):
        return reverse("recebimento_detalhe", args=[self.pk])

    @property
    def estornado(self):
        return self.estornado_em is not None


# ---------- Despesas ----------
class CategoriaDespesa(models.Model):
    nome = models.CharField("nome", max_length=80, unique=True)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "categoria de despesa"
        verbose_name_plural = "categorias de despesa"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("categoria_despesa_lista")


class DespesaQuerySet(models.QuerySet):
    def pagas(self):
        return self.filter(data_pagamento__isnull=False)

    def em_aberto(self):
        return self.filter(data_pagamento__isnull=True)


class Despesa(Auditavel):
    """Dinheiro que sai. `data_pagamento` vazia = em aberto (conta a pagar)."""

    descricao = models.CharField("descrição", max_length=150)
    categoria = models.ForeignKey(
        CategoriaDespesa, verbose_name="categoria", on_delete=models.PROTECT, related_name="despesas",
    )
    valor = models.DecimalField("valor (R$)", max_digits=10, decimal_places=2, validators=[VALOR_MINIMO])
    vencimento = models.DateField("vencimento", default=timezone.localdate)
    data_pagamento = models.DateField("data do pagamento", null=True, blank=True,
                                      help_text="Deixe em branco enquanto a despesa não foi paga.")
    forma_pagamento = models.CharField("forma de pagamento", max_length=15, choices=FormaPagamento.choices, blank=True)
    fornecedor = models.CharField("fornecedor", max_length=120, blank=True)
    observacao = models.TextField("observação", blank=True)
    comprovante = models.FileField(
        "comprovante", upload_to=caminho_comprovante, storage=armazenamento_privado, null=True, blank=True,
        help_text="PDF, JPG ou PNG, até 5 MB.",
    )
    tipo_servico = models.ForeignKey(
        TipoServico, verbose_name="serviço (despesa direta)", null=True, blank=True,
        on_delete=models.PROTECT, related_name="despesas",
        help_text="Preencha se a despesa pertence a um tipo de serviço (entra no lucro dele). "
                  "Em branco = despesa geral (aluguel, internet...).",
    )

    # Recorrência: a despesa marcada como "recorrente" é o modelo; as geradas apontam para ela em `origem`.
    recorrente = models.BooleanField(
        "repetir todo mês", default=False,
        help_text="Gera automaticamente as despesas dos próximos meses, no mesmo dia.",
    )
    origem = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="recorrencias", editable=False,
    )

    objects = DespesaQuerySet.as_manager()

    class Meta:
        verbose_name = "despesa"
        verbose_name_plural = "despesas"
        ordering = ["-vencimento", "-id"]
        indexes = [models.Index(fields=["vencimento"]), models.Index(fields=["data_pagamento"])]
        constraints = [
            models.CheckConstraint(condition=Q(valor__gt=0), name="despesa_valor_positivo"),
            # Garantia final contra duplicar a mesma recorrência no mesmo vencimento.
            models.UniqueConstraint(
                fields=["origem", "vencimento"], condition=Q(origem__isnull=False), name="despesa_recorrencia_unica"),
        ]

    def __str__(self):
        return self.descricao

    def get_absolute_url(self):
        return reverse("despesa_detalhe", args=[self.pk])

    @property
    def paga(self):
        return self.data_pagamento is not None

    @property
    def data_lancamento(self):
        """Data que vale para o fechamento de mês: o pagamento (se houve) ou o vencimento."""
        return self.data_pagamento or self.vencimento

    @property
    def situacao(self):
        if self.paga:
            return "paga"
        hoje = timezone.localdate()
        if self.vencimento < hoje:
            return "vencida"
        return "vence_hoje" if self.vencimento == hoje else "a_vencer"

    @property
    def situacao_texto(self):
        return {"paga": "Paga", "vencida": "Vencida", "vence_hoje": "Vence hoje", "a_vencer": "A vencer"}[self.situacao]

    @property
    def dias_de_atraso(self):
        return max((timezone.localdate() - self.vencimento).days, 0) if not self.paga else 0


# ---------- Fechamento de mês ----------
class FechamentoMes(models.Model):
    """Mês fechado não aceita criar, editar nem estornar lançamentos com data nele (até ser reaberto)."""

    mes = models.DateField("mês", unique=True, help_text="Sempre o primeiro dia do mês.")
    fechado = models.BooleanField("fechado", default=True)
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    fechado_em = models.DateTimeField(null=True, blank=True)
    reaberto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reaberto_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "fechamento de mês"
        verbose_name_plural = "fechamentos de mês"
        ordering = ["-mes"]
        permissions = [("fechar_mes", "Pode fechar e reabrir meses")]

    def __str__(self):
        return f"{self.mes:%m/%Y} ({'fechado' if self.fechado else 'reaberto'})"


# ---------- Auditoria ----------
class RegistroAuditoria(models.Model):
    """Trilha de auditoria do módulo: criações, alterações de valor, estornos, pagamentos, exclusões, fechamentos."""

    class Entidade(models.TextChoices):
        RECEBIMENTO = "recebimento", "Recebimento"
        DESPESA = "despesa", "Despesa"
        MES = "mes", "Mês"

    entidade = models.CharField("entidade", max_length=12, choices=Entidade.choices)
    objeto_id = models.PositiveIntegerField("objeto")
    acao = models.CharField("ação", max_length=20)
    descricao = models.TextField("descrição")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuário", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    data_hora = models.DateTimeField("data e hora", default=timezone.now)

    class Meta:
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        ordering = ["data_hora", "id"]
        indexes = [models.Index(fields=["entidade", "objeto_id"])]

    def __str__(self):
        return f"{self.get_entidade_display()} {self.objeto_id}: {self.acao}"
