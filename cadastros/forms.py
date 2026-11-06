from django import forms
from django.urls import reverse
from django.utils.html import format_html

from .models import Aluno, Cliente, Veiculo


class _DataInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nome", "cpf_cnpj", "telefone", "whatsapp", "email", "observacoes", "data_cadastro"]
        widgets = {"data_cadastro": _DataInput(), "observacoes": forms.Textarea(attrs={"rows": 3})}
        error_messages = {
            "nome": {"required": "Informe o nome do cliente."},
            "telefone": {"required": "Informe um telefone para contato."},
        }


class AlunoForm(forms.ModelForm):
    class Meta:
        model = Aluno
        fields = (
            ["nome", "cpf", "email", "data_nascimento", "sexo", "celular", "endereco", "cep",
             "cliente", "observacoes", "data_cadastro"]
            + [campo for campo, _ in Aluno.DOCUMENTOS]
        )
        widgets = {
            "data_cadastro": _DataInput(),
            "data_nascimento": _DataInput(),
            "sexo": forms.RadioSelect(),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
            # FileInput simples: não exibe o link direto do arquivo (ele é protegido por login).
            **{campo: forms.FileInput() for campo, _ in Aluno.DOCUMENTOS},
        }
        error_messages = {
            "nome": {"required": "Informe o nome do aluno."},
            "cpf": {"required": "Informe o CPF do aluno."},
            "data_nascimento": {"required": "Informe a data de nascimento.", "invalid": "Data inválida."},
            "sexo": {"required": "Selecione feminino ou masculino."},
            "celular": {"required": "Informe o celular do aluno."},
            "endereco": {"required": "Informe o endereço."},
            "cep": {"required": "Informe o CEP."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sexo"].choices = Aluno.Sexo.choices  # sem a opção vazia "---------"
        # Para cada documento: mostra link do arquivo atual e opção de removê-lo.
        ordem = []
        for campo, rotulo in Aluno.DOCUMENTOS:
            ordem.append(campo)
            if self.instance.pk and getattr(self.instance, campo):
                url = reverse("aluno_documento", args=[self.instance.pk, campo])
                self.fields[campo].help_text = format_html(
                    '{} <br>Arquivo atual: <a href="{}" target="_blank">abrir</a>. '
                    "Enviar outro arquivo substitui o atual.",
                    self.fields[campo].help_text, url,
                )
                self.fields[f"remover_{campo}"] = forms.BooleanField(
                    required=False, label=f"Remover arquivo: {rotulo.lower()}",
                )
                ordem.append(f"remover_{campo}")
        base = [n for n in self.fields if n not in ordem]
        self.order_fields(base + ordem)

    def save(self, commit=True):
        # Guarda os arquivos antigos para apagá-los do disco se forem trocados ou removidos.
        antigos = {}
        if self.instance.pk:
            anterior = Aluno.objects.get(pk=self.instance.pk)
            antigos = {campo: getattr(anterior, campo) for campo, _ in Aluno.DOCUMENTOS}
        for campo, _ in Aluno.DOCUMENTOS:
            if self.cleaned_data.get(f"remover_{campo}") and campo not in self.files:
                setattr(self.instance, campo, "")
        aluno = super().save(commit)
        if commit:
            for campo, antigo in antigos.items():
                if antigo and antigo.name != getattr(aluno, campo).name:
                    antigo.delete(save=False)
        return aluno


class VeiculoForm(forms.ModelForm):
    class Meta:
        model = Veiculo
        fields = ["placa", "marca", "modelo", "ano", "cor", "chassi", "proprietario", "observacoes"]
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 3})}
        error_messages = {
            "placa": {"required": "Informe a placa do veículo."},
            "marca": {"required": "Informe a marca."},
            "modelo": {"required": "Informe o modelo."},
            "ano": {"required": "Informe o ano.", "invalid": "Informe um ano válido (somente números)."},
            "cor": {"required": "Informe a cor."},
            "proprietario": {"required": "Selecione o proprietário (cliente)."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proprietario"].empty_label = "Selecione o cliente"
        self.fields["placa"].widget.attrs["placeholder"] = "ABC1D23"
