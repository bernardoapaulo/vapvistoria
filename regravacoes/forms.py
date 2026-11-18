from io import BytesIO

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageOps

from cadastros.models import Cliente
from servicos.models import TipoServico
from vip_preparacao.models import Cor

from . import anexos as processamento
from . import regras
from .models import AnexoRegravacao, ConfiguracaoEmpresa, Parceiro, RegistroRegravacao, Tecnico

Tipo = AnexoRegravacao.Tipo
Situacao = RegistroRegravacao.Situacao


class _DataInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


def nome_campo_anexo(tipo):
    return f"anexo_{tipo}"


def nome_campo_remover(tipo):
    return f"remover_anexo_{tipo}"


class RegistroRegravacaoForm(forms.ModelForm):
    class Meta:
        model = RegistroRegravacao
        fields = [
            "parceiro", "cliente", "placa", "marca", "modelo", "ano_modelo", "cor", "cor_outra", "chassi",
            "numero_motor", "proprietario", "proprietario_e_cliente", "servico_motor", "servico_chassi",
            "data_agendada", "data_concluida", "valor", "recebimento_situacao", "forma_pagamento",
            "data_recebimento", "tecnico", "observacao",
        ]
        widgets = {
            "data_agendada": _DataInput(), "data_concluida": _DataInput(), "data_recebimento": _DataInput(),
            "observacao": forms.Textarea(attrs={"rows": 3}),
            "placa": forms.TextInput(attrs={"autocapitalize": "characters", "maxlength": 8}),
            "chassi": forms.TextInput(attrs={"autocapitalize": "characters", "maxlength": 17}),
            "ano_modelo": forms.TextInput(attrs={"placeholder": "2011/2012", "maxlength": 9, "inputmode": "numeric"}),
            "valor": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"}),
        }
        error_messages = {
            "cliente": {"required": "Selecione o cliente indicado."},
            "placa": {"required": "Informe a placa do veículo."},
            "data_agendada": {"invalid": "Data inválida."},
            "data_concluida": {"invalid": "Data inválida."},
            "data_recebimento": {"invalid": "Data inválida."},
            "valor": {"invalid": "Informe um valor válido, por exemplo 450.00."},
        }

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        atual = self.instance if self.instance.pk else None
        self._antes = regras.estado(atual) if atual else None
        self.fields["parceiro"].queryset = Parceiro.objects.filter(Q(ativo=True) | Q(pk=atual.parceiro_id if atual else None)).order_by("nome")
        self.fields["tecnico"].queryset = Tecnico.objects.filter(Q(ativo=True) | Q(pk=atual.tecnico_id if atual else None)).order_by("nome")
        self.fields["cliente"].queryset = Cliente.objects.order_by("nome")
        self.fields["cor"].choices = [("", "Selecione...")] + list(Cor.choices)
        self.fields["cor_outra"].label = "Descreva a cor"
        self.fields["forma_pagamento"].choices = [("", "Selecione...")] + list(self.fields["forma_pagamento"].choices)[1:]
        self.fields["recebimento_situacao"].widget = forms.RadioSelect(choices=Situacao.choices)
        self.fields["proprietario"].required = False
        # Só quem tem a permissão altera o valor; o servidor ignora o que vier dos demais.
        self.pode_alterar_valor = usuario.has_perm("regravacoes.alterar_valor_regravacao")
        if not self.pode_alterar_valor:
            self.fields["valor"].disabled = True
        for tipo, rotulo in Tipo.choices:
            self.fields[nome_campo_anexo(tipo)] = forms.FileField(
                label=rotulo, required=False,
                widget=forms.FileInput(attrs={"accept": "application/pdf,image/*,.heic,.heif", "data-anexo": "1"}))
            self.fields[nome_campo_remover(tipo)] = forms.BooleanField(label="Remover", required=False)

    def clean(self):
        dados = super().clean()
        self.anexos_novos, self.anexos_remover = {}, set()
        for tipo, _ in Tipo.choices:
            arquivo = dados.get(nome_campo_anexo(tipo))
            if arquivo:
                try:
                    self.anexos_novos[tipo] = processamento.processar(arquivo)
                except ValidationError as e:
                    self.add_error(nome_campo_anexo(tipo), e)
            elif dados.get(nome_campo_remover(tipo)):
                self.anexos_remover.add(tipo)
        return dados

    def campos_de_anexos(self, existentes):
        """Para o template: um dicionário por tipo (campo, remover, anexo atual e se é exigido)."""
        exigidos = set(self.instance.anexos_exigidos) if self.instance.pk else set()
        return [{"tipo": tipo, "rotulo": rotulo, "campo": self[nome_campo_anexo(tipo)],
                 "remover": self[nome_campo_remover(tipo)], "anexo": existentes.get(tipo), "exigido": tipo in exigidos}
                for tipo, rotulo in Tipo.choices]

    @transaction.atomic
    def salvar(self):
        """Grava o registro e os anexos e, se estiver concluída e recebida, lança no Financeiro (tudo ou nada)."""
        novo = self.instance.pk is None
        r = self.save(commit=False)
        if novo:
            r.criado_por = self.usuario
        r.alterado_por = self.usuario
        r.save()
        if novo:
            regras.registrar_criacao(r, self.usuario)
        else:
            regras.registrar_edicao(r, self._antes, self.usuario)
        regras.salvar_anexos(r, self.anexos_novos, self.anexos_remover, self.usuario)
        regras.lancar(r, self.usuario)
        return r


class ConcluirRegravacaoForm(forms.Form):
    """Pop-up "Concluir / receber": data do serviço, técnico e recebimento."""
    data_concluida = forms.DateField(label="Data do serviço concluído", widget=_DataInput(), required=False,
                                     error_messages={"invalid": "Data inválida."})
    tecnico = forms.ModelChoiceField(label="Técnico responsável", queryset=Tecnico.objects.none(), required=False)
    situacao = forms.ChoiceField(label="Recebimento", choices=Situacao.choices, required=False)
    forma = forms.ChoiceField(label="Forma de pagamento", required=False)
    data_recebimento = forms.DateField(label="Data do recebimento", widget=_DataInput(), required=False,
                                       error_messages={"invalid": "Data inválida."})

    def __init__(self, *args, registro, **kwargs):
        super().__init__(*args, **kwargs)
        from financeiro.models import FormaPagamento
        self.fields["forma"].choices = [("", "Selecione...")] + list(FormaPagamento.choices)
        self.fields["tecnico"].queryset = Tecnico.objects.filter(Q(ativo=True) | Q(pk=registro.tecnico_id)).order_by("nome")
        hoje = timezone.localdate()
        self.initial = {"data_concluida": registro.data_concluida or hoje, "tecnico": registro.tecnico_id,
                        "situacao": registro.recebimento_situacao, "forma": registro.forma_pagamento,
                        "data_recebimento": registro.data_recebimento or hoje}


class FiltroRegravacaoForm(forms.Form):
    """Só valida o que vem na URL; a consulta é montada na view."""
    CAMPOS_DATA = [("criado_em", "Data do cadastro"), ("data_agendada", "Data agendada"),
                   ("data_concluida", "Data concluída"), ("data_recebimento", "Data do recebimento")]
    ORDENS = [("-criado_em", "Cadastro (mais recente)"), ("criado_em", "Cadastro (mais antigo)"),
              ("-data_concluida", "Concluída (mais recente)"), ("data_agendada", "Agendada (mais próxima)"),
              ("placa", "Placa"), ("cliente__nome", "Cliente"), ("-valor", "Valor (maior)")]
    de = forms.DateField(required=False)
    ate = forms.DateField(required=False)
    parceiro = forms.ModelChoiceField(queryset=Parceiro.objects.all(), required=False)
    tecnico = forms.ModelChoiceField(queryset=Tecnico.objects.all(), required=False)
    campo_data = forms.ChoiceField(choices=CAMPOS_DATA, required=False)
    ordem = forms.ChoiceField(choices=ORDENS, required=False)


class ParceiroForm(forms.ModelForm):
    class Meta:
        model = Parceiro
        fields = ["nome", "telefone", "empresa_profissao", "observacoes", "ativo"]
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 3})}
        error_messages = {"nome": {"required": "Informe o nome do parceiro."}}


class TecnicoForm(forms.ModelForm):
    class Meta:
        model = Tecnico
        fields = ["nome", "funcao", "credencial", "ativo"]
        error_messages = {"nome": {"required": "Informe o nome completo do técnico."}}


class EmpresaForm(forms.ModelForm):
    logo_nova = forms.FileField(label="Logo (PNG ou JPG)", required=False,
                                widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg"}))
    remover_logo = forms.BooleanField(label="Voltar a usar a logo padrão do sistema", required=False)

    class Meta:
        model = ConfiguracaoEmpresa
        fields = ["razao_social", "cnpj", "endereco", "telefones", "cidade", "rodape", "responsavel_recibo_nome",
                  "responsavel_recibo_funcao", "servico_motor", "servico_chassi", "servico_motor_chassi"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        regravacao = TipoServico.objects.filter(categoria=TipoServico.Categoria.REGRAVACAO).order_by("nome")
        for campo in ("servico_motor", "servico_chassi", "servico_motor_chassi"):
            self.fields[campo].queryset = regravacao
        self.fields["cidade"].help_text = "Aparece antes da data, no alto da declaração e do recibo."

    def clean_logo_nova(self):
        arquivo = self.cleaned_data.get("logo_nova")
        if not arquivo:
            return None
        if arquivo.size > 3 * 1024 * 1024:
            raise ValidationError("Logo muito grande. O tamanho máximo é 3 MB.")
        try:
            with Image.open(arquivo) as imagem:
                if imagem.format not in ("PNG", "JPEG"):
                    raise ValidationError("Envie a logo em PNG ou JPG.")
                imagem = ImageOps.exif_transpose(imagem).convert("RGBA")
                imagem.thumbnail((900, 900))
                saida = BytesIO()
                imagem.save(saida, "PNG", optimize=True)
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("O arquivo enviado não é uma imagem válida. Envie PNG ou JPG.")
        return saida.getvalue()

    def save(self, commit=True):
        cfg = super().save(commit=False)
        if self.cleaned_data.get("logo_nova"):
            cfg.logo, cfg.logo_tipo = self.cleaned_data["logo_nova"], "image/png"
        elif self.cleaned_data.get("remover_logo"):
            cfg.logo, cfg.logo_tipo = None, ""
        if commit:
            cfg.save()
        return cfg
