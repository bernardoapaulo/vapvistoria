import os
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from atendimentos.models import Atendimento
from dashboard import periodos
from dashboard.services import SALDO

from . import regras
from .dinheiro import reais
from .models import CategoriaDespesa, Despesa, FormaPagamento

LIMITE_COMPROVANTE = 5 * 1024 * 1024  # 5 MB
ASSINATURAS = {  # extensão -> primeiros bytes do arquivo (confere o conteúdo, não só o nome)
    ".pdf": (b"%PDF",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}


class _DataInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


def _valor(label="Valor (R$)"):
    return forms.DecimalField(
        label=label, max_digits=10, decimal_places=2, min_value=Decimal("0.01"),
        error_messages={
            "required": "Informe o valor.", "invalid": "Informe um valor válido, por exemplo 150.00.",
            "min_value": "O valor deve ser maior que zero.",
            "max_decimal_places": "Use no máximo 2 casas decimais (centavos).",
            "max_digits": "Valor muito grande.",
        },
    )


def validar_comprovante(arquivo):
    """PDF, JPG ou PNG de até 5 MB, e o conteúdo precisa combinar com a extensão."""
    extensao = os.path.splitext(arquivo.name)[1].lower()
    if extensao not in ASSINATURAS:
        raise ValidationError("Tipo de arquivo não permitido. Envie um PDF, JPG ou PNG.")
    if arquivo.size > LIMITE_COMPROVANTE:
        raise ValidationError("O arquivo é maior que 5 MB.")
    cabecalho = arquivo.read(8)
    arquivo.seek(0)
    if not any(cabecalho.startswith(a) for a in ASSINATURAS[extensao]):
        raise ValidationError("O conteúdo do arquivo não corresponde ao tipo informado.")


# ---------- Recebimentos ----------
def atendimentos_com_saldo():
    return (
        Atendimento.objects.exclude(status=Atendimento.Status.CANCELADO).annotate(saldo=SALDO).filter(saldo__gt=0)
        .select_related("cliente", "tipo_servico").order_by("-data_atendimento", "-id")
    )


class RecebimentoForm(forms.Form):
    """
    Registra um recebimento. Com `atendimento` o campo de atendimento some (tela do atendimento).
    Quem não pode editar recebimentos (Funcionário) não escolhe a data: vale sempre hoje.
    """
    atendimento = forms.ModelChoiceField(
        label="Atendimento", queryset=Atendimento.objects.none(),
        error_messages={"required": "Escolha o atendimento.", "invalid_choice": "Atendimento inválido."})
    valor = _valor()
    data = forms.DateField(
        label="Data do recebimento", widget=_DataInput(), required=False,
        error_messages={"invalid": "Data inválida."}, help_text="Em branco = hoje.")
    forma = forms.ChoiceField(
        label="Forma de pagamento", choices=FormaPagamento.choices,
        error_messages={"required": "Escolha a forma de pagamento.", "invalid_choice": "Forma de pagamento inválida."})
    observacao = forms.CharField(label="Observação", max_length=300, required=False)

    def __init__(self, *args, usuario, atendimento=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.atendimento = atendimento
        if atendimento is not None:
            del self.fields["atendimento"]
            self.fields["valor"].initial = max(atendimento.valor_em_aberto, Decimal("0.00"))
        else:
            self.fields["atendimento"].queryset = atendimentos_com_saldo()
            self.fields["atendimento"].label_from_instance = lambda a: (
                f"#{a.pk} · {a.data_atendimento:%d/%m/%Y} · {a.cliente.nome} · {a.tipo_servico.nome} · saldo {reais(a.saldo)}")
        if not usuario.has_perm("financeiro.change_recebimento"):
            del self.fields["data"]

    def salvar(self):
        """Chama a regra de negócio; erro dela vira erro do formulário. Retorna o recebimento ou None."""
        c = self.cleaned_data
        atendimento = self.atendimento or c["atendimento"]
        try:
            return regras.registrar_recebimento(
                atendimento, c["valor"], c.get("data") or timezone.localdate(), c["forma"], c["observacao"], self.usuario)
        except ValidationError as erro:
            self.add_error(None, erro)
            return None


class RecebimentoEdicaoForm(forms.Form):
    valor = _valor()
    data = forms.DateField(label="Data do recebimento", widget=_DataInput(), error_messages={
        "required": "Informe a data.", "invalid": "Data inválida."})
    forma = forms.ChoiceField(label="Forma de pagamento", choices=FormaPagamento.choices)
    observacao = forms.CharField(label="Observação", max_length=300, required=False)

    def __init__(self, *args, recebimento, usuario, **kwargs):
        kwargs.setdefault("initial", {
            "valor": recebimento.valor, "data": recebimento.data, "forma": recebimento.forma,
            "observacao": recebimento.observacao})
        super().__init__(*args, **kwargs)
        self.recebimento, self.usuario = recebimento, usuario

    def salvar(self):
        c = self.cleaned_data
        try:
            return regras.editar_recebimento(
                self.recebimento, c["valor"], c["data"], c["forma"], c["observacao"], self.usuario)
        except ValidationError as erro:
            self.add_error(None, erro)
            return None


class EstornoForm(forms.Form):
    motivo = forms.CharField(
        label="Motivo do estorno", max_length=300, widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Informe o motivo do estorno."})


# ---------- Despesas ----------
class DespesaForm(forms.ModelForm):
    class Meta:
        model = Despesa
        fields = [
            "descricao", "categoria", "tipo_servico", "valor", "vencimento", "data_pagamento",
            "forma_pagamento", "fornecedor", "observacao", "comprovante", "recorrente",
        ]
        widgets = {
            "vencimento": _DataInput(), "data_pagamento": _DataInput(),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }
        error_messages = {
            "descricao": {"required": "Informe a descrição."},
            "categoria": {"required": "Escolha a categoria."},
            "valor": {"required": "Informe o valor.", "invalid": "Informe um valor válido, por exemplo 150.00."},
            "vencimento": {"required": "Informe o vencimento.", "invalid": "Data inválida."},
            "data_pagamento": {"invalid": "Data inválida."},
        }

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        antes = self.instance if self.instance.pk else None
        self._foto = regras.foto_despesa(antes) if antes else None
        self._data_antes = antes.data_lancamento if antes else None
        self.fields["categoria"].queryset = CategoriaDespesa.objects.filter(ativa=True) | CategoriaDespesa.objects.filter(
            pk=antes.categoria_id if antes else None)
        self.fields["categoria"].empty_label = "Selecione a categoria"
        self.fields["tipo_servico"].empty_label = "Despesa geral (sem serviço)"
        self.fields["valor"].min_value = Decimal("0.01")
        self.fields["comprovante"].validators.append(validar_comprovante)
        if antes and antes.origem_id:  # despesa gerada pela recorrência: a repetição é controlada no modelo
            del self.fields["recorrente"]

    def clean(self):
        dados = super().clean()
        if self.errors:
            return dados
        # Monta uma cópia com os valores novos só para validar (a instância ainda não foi alterada).
        d = Despesa(vencimento=dados["vencimento"], data_pagamento=dados.get("data_pagamento"),
                    forma_pagamento=dados.get("forma_pagamento", ""))
        try:
            regras.validar_despesa(self._data_antes, d)
        except ValidationError as erro:
            self.add_error(None, erro)
        return dados

    def save(self, commit=True):
        despesa = super().save(commit=False)
        if not despesa.data_pagamento:
            despesa.forma_pagamento = ""
        return regras.salvar_despesa(despesa, self._foto, self.usuario)


class PagarDespesaForm(forms.Form):
    forma = forms.ChoiceField(
        label="Forma de pagamento", choices=FormaPagamento.choices,
        error_messages={"required": "Escolha a forma de pagamento.", "invalid_choice": "Forma de pagamento inválida."})
    data = forms.DateField(label="Data do pagamento", required=False, widget=_DataInput(),
                           error_messages={"invalid": "Data inválida."}, help_text="Em branco = hoje.")

    def clean_data(self):
        return self.cleaned_data.get("data") or timezone.localdate()


class CategoriaDespesaForm(forms.ModelForm):
    class Meta:
        model = CategoriaDespesa
        fields = ["nome", "ativa"]
        error_messages = {
            "nome": {"required": "Informe o nome da categoria.", "unique": "Já existe uma categoria com este nome."},
        }


# ---------- Filtros (GET) ----------
class FiltroPeriodoForm(forms.Form):
    """Mesmos períodos do dashboard de desempenho. Valores inválidos são ignorados, nunca quebram a tela."""
    periodo = forms.ChoiceField(label="Período", choices=periodos.OPCOES, required=False)
    de = forms.DateField(label="De", required=False)
    ate = forms.DateField(label="Até", required=False)

    def periodo_escolhido(self):
        self.is_valid()
        dados = getattr(self, "cleaned_data", {})
        return periodos.calcular(dados.get("periodo") or periodos.ESTE_MES, dados.get("de"), dados.get("ate"))
