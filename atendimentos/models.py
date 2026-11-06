from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Aluno, Cliente, Veiculo
from servicos.models import TipoServico

ZERO = Decimal("0.00")
CATEGORIA = TipoServico.Categoria


class AtendimentoQuerySet(models.QuerySet):
    def em_aberto(self):
        return self.filter(status__in=Atendimento.STATUS_ABERTOS)

    def nao_cancelados(self):
        return self.exclude(status=Atendimento.Status.CANCELADO)

    def totais(self):
        """Total cobrado (já com desconto) e total pago, ignorando cancelados."""
        valor_final = ExpressionWrapper(
            F("valor_cobrado") - F("desconto"), output_field=DecimalField(max_digits=12, decimal_places=2)
        )
        r = self.nao_cancelados().aggregate(total=Sum(valor_final), pago=Sum("valor_pago"))
        total, pago = r["total"] or ZERO, r["pago"] or ZERO
        return {"total": total, "pago": pago, "em_aberto": total - pago}


class Atendimento(models.Model):
    """Um serviço solicitado ou prestado. Base do dashboard e do financeiro."""

    class Status(models.TextChoices):
        SOLICITADO = "solicitado", "Solicitado"
        AGENDADO = "agendado", "Agendado"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDO = "concluido", "Concluído"
        CANCELADO = "cancelado", "Cancelado"

    class SituacaoPagamento(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PARCIAL = "parcial", "Parcial"
        PAGO = "pago", "Pago"

    STATUS_ABERTOS = [Status.SOLICITADO, Status.AGENDADO, Status.EM_ANDAMENTO]
    STATUS_FECHADOS = [Status.CONCLUIDO, Status.CANCELADO]

    # Fluxo permitido. Sair de Concluído/Cancelado é "reabrir" (só Administrador).
    TRANSICOES = {
        Status.SOLICITADO: [Status.AGENDADO, Status.EM_ANDAMENTO, Status.CANCELADO],
        Status.AGENDADO: [Status.EM_ANDAMENTO, Status.CANCELADO],
        Status.EM_ANDAMENTO: [Status.CONCLUIDO, Status.CANCELADO],
        Status.CONCLUIDO: [Status.EM_ANDAMENTO],
        Status.CANCELADO: [Status.EM_ANDAMENTO],
    }

    cliente = models.ForeignKey(Cliente, verbose_name="cliente", on_delete=models.PROTECT, related_name="atendimentos")
    tipo_servico = models.ForeignKey(
        TipoServico, verbose_name="tipo de serviço", on_delete=models.PROTECT, related_name="atendimentos",
    )
    veiculo = models.ForeignKey(
        Veiculo, verbose_name="veículo", null=True, blank=True, on_delete=models.PROTECT,
        related_name="atendimentos",
    )
    aluno = models.ForeignKey(
        Aluno, verbose_name="aluno", null=True, blank=True, on_delete=models.PROTECT,
        related_name="atendimentos",
    )
    data_atendimento = models.DateField("data do atendimento", default=date.today)

    # O valor é copiado do tipo de serviço na criação e guardado aqui: mudar o
    # valor padrão do serviço no futuro não altera atendimentos antigos.
    valor_cobrado = models.DecimalField(
        "valor cobrado (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(ZERO, "O valor não pode ser negativo.")],
    )
    desconto = models.DecimalField(
        "desconto (R$)", max_digits=10, decimal_places=2, default=ZERO,
        validators=[MinValueValidator(ZERO, "O desconto não pode ser negativo.")],
    )

    # O pagamento é CALCULADO a partir dos recebimentos (app financeiro): estes dois campos são só
    # uma cópia para consultas rápidas e quem os grava é financeiro.regras.recalcular_pagamento().
    situacao_pagamento = models.CharField(
        "situação do pagamento", max_length=10, choices=SituacaoPagamento.choices,
        default=SituacaoPagamento.PENDENTE, editable=False,
    )
    valor_pago = models.DecimalField(
        "valor pago (R$)", max_digits=10, decimal_places=2, default=ZERO, editable=False,
        help_text="Soma dos recebimentos não estornados.",
    )
    revisar_pagamento = models.BooleanField(
        "pagamento a revisar", default=False,
        help_text="Marcado pela migração quando o pagamento antigo não tinha dados suficientes.",
    )

    status = models.CharField("status", max_length=15, choices=Status.choices, default=Status.SOLICITADO)
    observacoes = models.TextField("observações", blank=True)

    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="registrado por", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    objects = AtendimentoQuerySet.as_manager()

    class Meta:
        verbose_name = "atendimento"
        verbose_name_plural = "atendimentos"
        ordering = ["-data_atendimento", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["data_atendimento"]),
        ]
        permissions = [
            ("alterar_valor", "Pode alterar o valor cobrado e o desconto"),
            ("reabrir", "Pode reabrir atendimento concluído ou cancelado"),
            # Usadas pelo dashboard (valores e exportação são só do Administrador)
            ("ver_faturamento", "Pode ver faturamento e valores no dashboard"),
            ("exportar_dados", "Pode exportar dados em CSV"),
        ]

    def __str__(self):
        return f"#{self.pk} - {self.tipo_servico} - {self.cliente}"

    def get_absolute_url(self):
        return reverse("atendimento_detalhe", args=[self.pk])

    # ---------- Propriedades de apoio ----------
    @property
    def valor_final(self):
        return (self.valor_cobrado or ZERO) - (self.desconto or ZERO)

    @property
    def valor_em_aberto(self):
        return self.valor_final - (self.valor_pago or ZERO)

    @property
    def dias_de_atraso(self):
        """Dias desde a data do atendimento (o "vencimento" do que falta receber)."""
        return max((timezone.localdate() - self.data_atendimento).days, 0)

    @property
    def aberto(self):
        return self.status in self.STATUS_ABERTOS

    @property
    def fechado(self):
        return self.status in self.STATUS_FECHADOS

    @staticmethod
    def categoria_exige_aluno(categoria):
        return categoria == CATEGORIA.CAPACITACAO

    def pode_ir_para(self, novo_status):
        return novo_status in self.TRANSICOES.get(self.status, [])

    # ---------- Regras de negócio ----------
    def clean(self):
        erros = {}

        # Veículo ou aluno conforme a categoria do serviço
        if self.tipo_servico_id:
            categoria = self.tipo_servico.categoria
            nome_categoria = self.tipo_servico.get_categoria_display()
            if self.categoria_exige_aluno(categoria):
                if not self.aluno_id:
                    erros["aluno"] = f"Informe o aluno: o serviço de {nome_categoria.lower()} é feito por um aluno."
                if self.veiculo_id:
                    erros["veiculo"] = "Veículo não se aplica a capacitação. Deixe este campo em branco."
            else:
                if not self.veiculo_id:
                    erros["veiculo"] = f"Informe o veículo: o serviço de {nome_categoria.lower()} exige um veículo."
                elif self.cliente_id and self.veiculo.proprietario_id != self.cliente_id:
                    erros["veiculo"] = "O veículo selecionado não pertence ao cliente escolhido."
                if self.aluno_id:
                    erros["aluno"] = "Aluno só deve ser informado em atendimentos de capacitação."

        # Valores
        if self.valor_cobrado is not None and self.desconto is not None:
            if self.desconto > self.valor_cobrado:
                erros["desconto"] = "O desconto não pode ser maior que o valor cobrado."

        if erros:
            raise ValidationError(erros)


class HistoricoAtendimento(models.Model):
    """Registro automático de cada mudança importante de um atendimento."""

    class Tipo(models.TextChoices):
        CRIACAO = "criacao", "Criação"
        STATUS = "status", "Mudança de status"
        REABERTURA = "reabertura", "Reabertura"
        PAGAMENTO = "pagamento", "Pagamento"
        VALOR = "valor", "Alteração de valor"
        AGENDA = "agenda", "Agenda"

    atendimento = models.ForeignKey(Atendimento, on_delete=models.CASCADE, related_name="historico")
    tipo = models.CharField("tipo", max_length=12, choices=Tipo.choices)
    valor_anterior = models.CharField("de", max_length=200, blank=True)
    valor_novo = models.CharField("para", max_length=200)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuário", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    data_hora = models.DateTimeField("data e hora", default=timezone.now)

    class Meta:
        verbose_name = "histórico de atendimento"
        verbose_name_plural = "históricos de atendimento"
        ordering = ["data_hora", "id"]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.valor_anterior} -> {self.valor_novo}"
