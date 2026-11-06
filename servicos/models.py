from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


class TipoServico(models.Model):
    class Categoria(models.TextChoices):
        VISTORIA = "vistoria_cautelar", "Vistoria cautelar"
        REGRAVACAO = "regravacao", "Regravação"
        CAPACITACAO = "capacitacao", "Capacitação"
        LIMPEZA = "limpeza", "Limpeza"
        REPAROS = "pequenos_reparos", "Pequenos reparos"

    nome = models.CharField("nome", max_length=120)
    categoria = models.CharField("categoria", max_length=30, choices=Categoria.choices)
    valor_padrao = models.DecimalField(
        "valor padrão (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"), "O valor não pode ser negativo.")],
    )
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "tipo de serviço"
        verbose_name_plural = "tipos de serviço"
        ordering = ["categoria", "nome"]

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("servico_detalhe", args=[self.pk])
