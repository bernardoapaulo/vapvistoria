from django import forms

from .models import TipoServico


class TipoServicoForm(forms.ModelForm):
    class Meta:
        model = TipoServico
        fields = ["nome", "categoria", "valor_padrao", "ativo"]
        error_messages = {
            "nome": {"required": "Informe o nome do serviço."},
            "categoria": {"required": "Selecione a categoria."},
            "valor_padrao": {
                "required": "Informe o valor padrão.",
                "invalid": "Informe um valor válido, por exemplo 150.00.",
            },
        }
