"""
Módulo Vip/Preparação: veículos que entram para lavagem/estética (VIP) e/ou preparação.

O registro guarda os próprios dados do veículo (placa, marca...): um cliente pode ter vários carros e a
placa não precisa estar no cadastro de Veículos. Ao CONCLUIR, `regras.concluir` cria (ou reaproveita) o
Atendimento e lança o Recebimento no Financeiro, tudo em uma transação.
"""
import re
import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Cliente
from cadastros.validators import normalizar_placa, validar_placa
from atendimentos.models import Atendimento
from financeiro.models import Auditavel
from servicos.models import TipoServico

from .armazenamento import armazenamento_fotos

ZERO = Decimal("0.00")
CHASSI = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # 17 caracteres, sem I, O e Q


class Cor(models.TextChoices):
    BRANCO = "branco", "Branco"
    PRETO = "preto", "Preto"
    PRATA = "prata", "Prata"
    CINZA = "cinza", "Cinza"
    VERMELHO = "vermelho", "Vermelho"
    AZUL = "azul", "Azul"
    VERDE = "verde", "Verde"
    AMARELO = "amarelo", "Amarelo"
    LARANJA = "laranja", "Laranja"
    MARROM = "marrom", "Marrom"
    BEGE = "bege", "Bege"
    DOURADO = "dourado", "Dourado"
    VINHO = "vinho", "Vinho"
    OUTRA = "outra", "Outra"


def validar_chassi(valor):
    chassi = (valor or "").strip().upper()
    if chassi and not CHASSI.match(chassi):
        raise ValidationError(
            "Chassi inválido. Informe 17 letras e números, sem as letras I, O e Q.")


def ano_maximo():
    return date.today().year + 1


class RegistroVipQuerySet(models.QuerySet):
    def em_andamento(self):
        return self.filter(status=RegistroVip.Status.EM_ANDAMENTO)

    def concluidos(self):
        return self.filter(status=RegistroVip.Status.CONCLUIDO)


class RegistroVip(Auditavel):
    class Status(models.TextChoices):
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDO = "concluido", "Concluído"

    class Etapa(models.TextChoices):
        AGUARDANDO = "aguardando", "Aguardando preparação"
        PREPARACAO = "preparacao", "Em preparação"
        VIP = "vip", "VIP"
        PRONTO = "pronto", "Pronto para devolução"
        ATRASADA = "atrasada", "Devolução atrasada"
        CONCLUIDO = "concluido", "Concluído"

    cliente = models.ForeignKey(Cliente, verbose_name="cliente", on_delete=models.PROTECT, related_name="registros_vip")
    placa = models.CharField("placa", max_length=8, validators=[validar_placa])
    marca = models.CharField("marca", max_length=60, blank=True)
    modelo = models.CharField("modelo", max_length=80, blank=True)
    versao = models.CharField("versão", max_length=80, blank=True)
    cor = models.CharField("cor", max_length=15, choices=Cor.choices, blank=True)
    cor_outra = models.CharField("descrição da cor", max_length=30, blank=True)
    ano = models.PositiveSmallIntegerField(
        "ano", null=True, blank=True, validators=[MinValueValidator(1950, "Informe um ano a partir de 1950.")])
    chassi = models.CharField("chassi", max_length=17, blank=True, validators=[validar_chassi])

    data_preparacao = models.DateField("data de preparação")
    data_vip = models.DateField("data VIP", null=True, blank=True)
    data_devolucao = models.DateField("data de devolução", null=True, blank=True)

    # Total dos itens de serviço (calculado: quem grava é regras.recalcular_total, no padrão do valor_pago do
    # Atendimento). Guardado para a lista poder filtrar e ordenar por valor sem somar a cada linha.
    valor = models.DecimalField(
        "valor total (R$)", max_digits=10, decimal_places=2, default=ZERO, editable=False,
        validators=[MinValueValidator(ZERO, "O valor não pode ser negativo.")])
    previsao_pagamento = models.DateField("previsão de pagamento", null=True, blank=True)
    nota_fiscal = models.CharField("nota fiscal", max_length=40, blank=True)
    observacao = models.TextField("observação", blank=True)

    status = models.CharField("status", max_length=15, choices=Status.choices, default=Status.EM_ANDAMENTO)
    concluido_em = models.DateTimeField("concluído em", null=True, blank=True, editable=False)
    concluido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="concluído por", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+", editable=False)

    objects = RegistroVipQuerySet.as_manager()

    class Meta:
        verbose_name = "registro VIP/Preparação"
        verbose_name_plural = "registros VIP/Preparação"
        ordering = ["-data_preparacao", "-id"]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["placa"])]
        permissions = [
            ("alterar_valor_vip", "Pode alterar o valor do registro VIP/Preparação"),
            ("concluir_vip", "Pode concluir (e lançar o recebimento) do registro VIP/Preparação"),
            ("reabrir_vip", "Pode reabrir registro VIP/Preparação concluído"),
            ("editar_concluido_vip", "Pode editar todos os dados de um registro concluído"),
        ]

    def __str__(self):
        return f"VIP/Preparação #{self.pk} - {self.placa}"

    def get_absolute_url(self):
        return reverse("vip_detalhe", args=[self.pk])

    # ---------- Propriedades de apoio ----------
    @property
    def concluido(self):
        return self.status == self.Status.CONCLUIDO

    @property
    def lista_itens(self):
        """Itens já carregados (use prefetch_related("itens__servico") nas listagens)."""
        return list(self.itens.all())

    @property
    def total_itens(self):
        return sum((i.valor for i in self.lista_itens), ZERO)

    @property
    def servicos_texto(self):
        nomes = [i.servico.nome for i in self.lista_itens]
        return " + ".join(nomes)

    @property
    def itens_json(self):
        """Para o pop-up de conclusão (data-itens): [{nome, valor}] com ponto decimal."""
        import json
        return json.dumps([{"nome": i.servico.nome, "valor": str(i.valor)} for i in self.lista_itens])

    @property
    def atendimentos(self):
        """Atendimentos gerados na conclusão (um por item)."""
        return Atendimento.objects.filter(item_vip__registro=self)

    @property
    def cor_texto(self):
        if self.cor == Cor.OUTRA:
            return self.cor_outra or "Outra"
        return self.get_cor_display() if self.cor else ""

    @property
    def veiculo_texto(self):
        return " ".join(p for p in (self.marca, self.modelo, self.versao) if p)

    @property
    def etapa(self):
        """Etapa calculada das datas (só uma etiqueta informativa)."""
        if self.concluido:
            return self.Etapa.CONCLUIDO
        hoje = timezone.localdate()
        if self.data_devolucao and self.data_devolucao < hoje:
            return self.Etapa.ATRASADA
        if self.data_devolucao and self.data_devolucao == hoje:
            return self.Etapa.PRONTO
        if self.data_vip and self.data_vip <= hoje:
            return self.Etapa.VIP
        if self.data_preparacao <= hoje:
            return self.Etapa.PREPARACAO
        return self.Etapa.AGUARDANDO

    @property
    def etapa_texto(self):
        return self.Etapa(self.etapa).label

    @property
    def atrasado(self):
        return self.etapa == self.Etapa.ATRASADA

    # ---------- Regras ----------
    def clean(self):
        erros = {}
        self.placa = normalizar_placa(self.placa)
        self.chassi = (self.chassi or "").strip().upper()
        if self.ano and self.ano > ano_maximo():
            erros["ano"] = "O ano não pode estar tão no futuro."
        if self.cor == Cor.OUTRA and not (self.cor_outra or "").strip():
            erros["cor_outra"] = "Descreva a cor."
        if self.data_vip and self.data_preparacao and self.data_vip < self.data_preparacao:
            erros["data_vip"] = "A data VIP não pode ser anterior à data de preparação."
        if self.data_devolucao:
            minima = self.data_vip or self.data_preparacao
            if minima and self.data_devolucao < minima:
                rotulo = "data VIP" if self.data_vip else "data de preparação"
                erros["data_devolucao"] = f"A data de devolução não pode ser anterior à {rotulo}."
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        self.placa = normalizar_placa(self.placa)
        self.chassi = (self.chassi or "").strip().upper()
        super().save(*args, **kwargs)


class ItemServicoVip(models.Model):
    """Um serviço do registro. O mesmo serviço pode aparecer mais de uma vez (cada linha é um item)."""

    registro = models.ForeignKey(RegistroVip, on_delete=models.CASCADE, related_name="itens")
    servico = models.ForeignKey(
        TipoServico, verbose_name="serviço", on_delete=models.PROTECT, related_name="itens_vip")
    # Copiado do serviço ao incluir o item e guardado aqui: mudar o valor padrão depois não altera o passado.
    valor = models.DecimalField(
        "valor (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(ZERO, "O valor não pode ser negativo.")])
    observacao = models.CharField("observação", max_length=120, blank=True)
    # Atendimento concluído gerado para este item na conclusão (cada item vira um atendimento).
    atendimento = models.OneToOneField(
        Atendimento, verbose_name="atendimento gerado", null=True, blank=True, editable=False,
        on_delete=models.PROTECT, related_name="item_vip")

    class Meta:
        verbose_name = "item de serviço VIP/Preparação"
        verbose_name_plural = "itens de serviço VIP/Preparação"
        ordering = ["id"]

    def __str__(self):
        return f"{self.servico} ({self.valor})"


class FotoVip(models.Model):
    class Momento(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SAIDA = "saida", "Saída"

    class Posicao(models.TextChoices):
        PLACA = "placa", "Placa"
        FRENTE = "frente", "Frente"
        LATERAL_ESQUERDA = "lateral_esquerda", "Lateral esquerda/frente"
        LATERAL_DIREITA = "lateral_direita", "Lateral direita/trás"
        EXTRA_1 = "extra_1", "Extra 1"
        EXTRA_2 = "extra_2", "Extra 2"
        EXTRA_3 = "extra_3", "Extra 3"
        EXTRA_4 = "extra_4", "Extra 4"
        EXTRA_5 = "extra_5", "Extra 5"
        EXTRA_6 = "extra_6", "Extra 6"

    registro = models.ForeignKey(RegistroVip, on_delete=models.CASCADE, related_name="fotos")
    momento = models.CharField("momento", max_length=10, choices=Momento.choices)
    posicao = models.CharField("posição", max_length=20, choices=Posicao.choices)
    # Nomes aleatórios, fora de qualquer pasta pública; só a view protegida entrega os arquivos.
    imagem = models.FileField("foto", upload_to="vip/%Y/%m/", storage=armazenamento_fotos)
    miniatura = models.FileField("miniatura", upload_to="vip/mini/%Y/%m/", storage=armazenamento_fotos)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    enviado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "foto VIP/Preparação"
        verbose_name_plural = "fotos VIP/Preparação"
        ordering = ["momento", "id"]
        constraints = [
            models.UniqueConstraint(fields=["registro", "momento", "posicao"], name="uniq_foto_vip_posicao")]

    def __str__(self):
        return f"{self.get_momento_display()} - {self.get_posicao_display()} ({self.registro})"


class HistoricoVip(models.Model):
    """Registro automático de cada mudança importante (padrão do histórico dos Atendimentos)."""

    class Tipo(models.TextChoices):
        CRIACAO = "criacao", "Criação"
        EDICAO = "edicao", "Edição"
        CONCLUSAO = "conclusao", "Conclusão"
        REABERTURA = "reabertura", "Reabertura"
        FOTOS = "fotos", "Fotos"
        ITENS = "itens", "Serviços"

    registro = models.ForeignKey(RegistroVip, on_delete=models.CASCADE, related_name="historico")
    tipo = models.CharField("tipo", max_length=12, choices=Tipo.choices)
    valor_anterior = models.CharField("de", max_length=300, blank=True)
    valor_novo = models.CharField("para", max_length=300)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuário", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    data_hora = models.DateTimeField("data e hora", default=timezone.now)

    class Meta:
        verbose_name = "histórico VIP/Preparação"
        verbose_name_plural = "históricos VIP/Preparação"
        ordering = ["data_hora", "id"]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.valor_anterior} -> {self.valor_novo}"
