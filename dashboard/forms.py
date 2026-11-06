from django import forms
from django.contrib.auth import get_user_model

from servicos.models import TipoServico

from . import periodos
from .services import Filtros


class FiltroDashboardForm(forms.Form):
    """Filtros do topo da página (GET). Valores inválidos são ignorados, nunca quebram a tela."""
    periodo = forms.ChoiceField(label="Período", choices=periodos.OPCOES, required=False)
    de = forms.DateField(label="De", required=False)
    ate = forms.DateField(label="Até", required=False)
    categoria = forms.ChoiceField(
        label="Categoria", choices=[("", "Todas")] + TipoServico.Categoria.choices, required=False)
    responsavel = forms.ModelChoiceField(
        label="Responsável", queryset=get_user_model().objects.none(), required=False, empty_label="Todos")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsavel"].queryset = get_user_model().objects.filter(is_active=True).order_by("username")
        self.fields["responsavel"].label_from_instance = lambda u: u.get_username()

    def filtros(self):
        self.is_valid()  # preenche cleaned_data com os campos válidos, mesmo que outros falhem
        dados = getattr(self, "cleaned_data", {})  # formulário sem GET (primeira visita) não tem cleaned_data
        periodo = periodos.calcular(dados.get("periodo") or periodos.ESTE_MES, dados.get("de"), dados.get("ate"))
        responsavel = dados.get("responsavel")
        return Filtros(periodo, dados.get("categoria") or "", responsavel.pk if responsavel else None)
