from django import forms
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from cadastros.models import Cliente
from financeiro.models import FormaPagamento
from servicos.models import TipoServico

from . import fotos, regras
from .models import Cor, FotoVip, RegistroVip

Posicao = FotoVip.Posicao
Momento = FotoVip.Momento

# Serviços que NÃO se aplicam a veículo em VIP/Preparação (a capacitação é feita por aluno, sem veículo).
CATEGORIAS_FORA = [TipoServico.Categoria.CAPACITACAO]


def servicos_disponiveis(incluir_pk=None):
    """Serviços ATIVOS que podem ser escolhidos (mais o já escolhido, se depois foi inativado)."""
    return TipoServico.objects.filter(
        Q(ativo=True) & ~Q(categoria__in=CATEGORIAS_FORA) | Q(pk=incluir_pk)).order_by("nome")


def nome_campo_foto(momento, posicao):
    return f"foto_{momento}_{posicao}"


def nome_campo_remover(momento, posicao):
    return f"remover_{momento}_{posicao}"


class _DataInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class _FotosMixin:
    """Campos de foto (um por posição) e de remoção, mais o processamento no servidor."""
    momentos = (Momento.ENTRADA, Momento.SAIDA)
    permite_remover = True

    def _criar_campos_foto(self):
        for momento in self.momentos:
            for posicao, rotulo in Posicao.choices:
                self.fields[nome_campo_foto(momento, posicao)] = forms.FileField(
                    label=rotulo, required=False,
                    widget=forms.FileInput(attrs={"accept": "image/*,.heic,.heif", "data-foto": "1"}))
                if self.permite_remover:
                    self.fields[nome_campo_remover(momento, posicao)] = forms.BooleanField(
                        label="Remover", required=False)

    def _processar_fotos(self):
        self.fotos_novas, self.fotos_remover = {}, set()
        for momento in self.momentos:
            for posicao, _ in Posicao.choices:
                nome = nome_campo_foto(momento, posicao)
                arquivo = self.cleaned_data.get(nome)
                if arquivo:
                    try:
                        grande, mini, _ = fotos.processar(arquivo)
                    except forms.ValidationError as e:
                        self.add_error(nome, e)
                    else:
                        self.fotos_novas[(momento, posicao)] = (grande, mini)
                elif self.permite_remover and self.cleaned_data.get(nome_campo_remover(momento, posicao)):
                    self.fotos_remover.add((momento, posicao))

    def campos_de_fotos(self, momento, existentes=None):
        """Para o template: um dicionário por posição, com o campo de arquivo, o de remoção e a foto já gravada."""
        existentes = existentes or {}
        return [
            {"posicao": posicao, "rotulo": rotulo, "campo": self[nome_campo_foto(momento, posicao)],
             "remover": self[nome_campo_remover(momento, posicao)] if self.permite_remover else None,
             "foto": existentes.get((momento, posicao))}
            for posicao, rotulo in Posicao.choices]


class RegistroVipForm(_FotosMixin, forms.ModelForm):
    class Meta:
        model = RegistroVip
        fields = [
            "cliente", "placa", "marca", "modelo", "versao", "cor", "cor_outra", "ano", "chassi", "servico",
            "data_preparacao", "data_vip", "data_devolucao", "valor", "previsao_pagamento", "nota_fiscal",
            "observacao",
        ]
        widgets = {
            "data_preparacao": _DataInput(), "data_vip": _DataInput(), "data_devolucao": _DataInput(),
            "previsao_pagamento": _DataInput(),
            "observacao": forms.Textarea(attrs={"rows": 3}),
            "placa": forms.TextInput(attrs={"autocapitalize": "characters", "maxlength": 8}),
            "chassi": forms.TextInput(attrs={"autocapitalize": "characters", "maxlength": 17}),
            "ano": forms.NumberInput(attrs={"inputmode": "numeric"}),
        }
        error_messages = {
            "cliente": {"required": "Selecione o cliente."},
            "placa": {"required": "Informe a placa do veículo."},
            "servico": {"required": "Selecione o serviço."},
            "data_preparacao": {"required": "Informe a data de preparação (entrada do veículo).", "invalid": "Data inválida."},
            "data_vip": {"invalid": "Data inválida."},
            "data_devolucao": {"invalid": "Data inválida."},
            "previsao_pagamento": {"invalid": "Data inválida."},
            "valor": {"invalid": "Informe um valor válido, por exemplo 150.00."},
            "ano": {"invalid": "Informe um ano válido, por exemplo 2018."},
        }

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.pode_alterar_valor = usuario.has_perm("vip_preparacao.alterar_valor_vip")
        atual = self.instance if self.instance.pk else None
        self._antes = regras.estado(atual) if atual else None
        self._servico_antes = atual.servico_id if atual else None
        self.concluido = bool(atual and atual.concluido)

        self.fields["cliente"].queryset = Cliente.objects.order_by("nome")
        self.fields["servico"].queryset = servicos_disponiveis(self._servico_antes)
        self.fields["servico"].label_from_instance = lambda s: f"{s.nome} — R$ {s.valor_padrao}"
        self.fields["cor"].choices = [("", "Selecione...")] + list(Cor.choices)
        self.fields["cor_outra"].label = "Descreva a cor"
        if not atual:
            self.fields["data_preparacao"].initial = timezone.localdate()

        # Valor: só o Administrador altera; depois de concluído, só reabrindo. O servidor ignora o que vier.
        # Cliente e serviço também ficam travados depois de concluído (já geraram atendimento e recebimento).
        self.valor_travado = not self.pode_alterar_valor or self.concluido
        self.fields["valor"].required = False       # em branco = valor padrão do serviço (preenchido em clean)
        if self.valor_travado:
            self.fields["valor"].disabled = True
        if self.concluido:
            for nome in ("cliente", "servico"):
                self.fields[nome].disabled = True
        self._criar_campos_foto()

    def clean_ano(self):
        ano = self.cleaned_data.get("ano")
        if ano is not None and ano > timezone.localdate().year + 1:
            raise forms.ValidationError("O ano não pode estar tão no futuro.")
        return ano

    def clean(self):
        dados = super().clean()
        servico = dados.get("servico")
        if self.valor_travado and servico:
            # novo registro, ou serviço trocado: vale o valor padrão do serviço; senão mantém o do registro
            if self.instance.pk and servico.pk == self._servico_antes:
                dados["valor"] = self.instance.valor
            else:
                dados["valor"] = servico.valor_padrao
        elif dados.get("valor") is None and servico and not self.errors.get("valor"):
            dados["valor"] = servico.valor_padrao   # administrador deixou em branco
        self._processar_fotos()
        return dados

    def nota_fiscal_repetida(self):
        nota = (self.cleaned_data.get("nota_fiscal") or "").strip()
        if not nota:
            return False
        return RegistroVip.objects.filter(nota_fiscal__iexact=nota).exclude(pk=self.instance.pk).exists()

    @transaction.atomic
    def salvar(self):
        novo = self.instance.pk is None
        r = self.save(commit=False)
        if novo:
            r.criado_por = self.usuario
        r.alterado_por = self.usuario
        r.nota_fiscal = (r.nota_fiscal or "").strip()
        r.save()
        if novo:
            regras.registrar_criacao(r, self.usuario)
        else:
            regras.registrar_edicao(r, self._antes, self.usuario)
        regras.salvar_fotos(r, self.fotos_novas, self.fotos_remover, self.usuario)
        return r


class FotosSaidaForm(_FotosMixin, forms.Form):
    """Registro já concluído, para quem não pode editá-lo por inteiro: só acrescenta fotos de saída."""
    momentos = (Momento.SAIDA,)
    permite_remover = False

    def __init__(self, *args, registro, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.registro, self.usuario = registro, usuario
        self._criar_campos_foto()

    def clean(self):
        dados = super().clean()
        self._processar_fotos()
        # nesta tela não se troca nem se remove: só posições ainda vazias
        ocupadas = set(self.registro.fotos.filter(momento=Momento.SAIDA).values_list("posicao", flat=True))
        for (momento, posicao) in list(self.fotos_novas):
            if posicao in ocupadas:
                self.add_error(nome_campo_foto(momento, posicao),
                               "Já existe uma foto nesta posição. Para trocar, o registro precisa ser reaberto.")
        return dados

    def salvar(self):
        regras.salvar_fotos(self.registro, self.fotos_novas, set(), self.usuario)


class ConcluirVipForm(forms.Form):
    valor = forms.DecimalField(
        label="Valor recebido (R$)", max_digits=10, decimal_places=2, min_value=0,
        error_messages={"invalid": "Informe um valor válido, por exemplo 150.00."})
    forma = forms.ChoiceField(label="Forma de pagamento", choices=[("", "Selecione...")] + list(FormaPagamento.choices),
                              error_messages={"required": "Informe a forma de pagamento."})
    data = forms.DateField(label="Data do recebimento", widget=_DataInput(), required=False,
                           error_messages={"invalid": "Data inválida."})

    def __init__(self, *args, registro, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.registro, self.usuario = registro, usuario
        self.pode_alterar_valor = usuario.has_perm("vip_preparacao.alterar_valor_vip")
        self.fields["valor"].initial = registro.valor
        self.fields["data"].initial = timezone.localdate()
        if not self.pode_alterar_valor:
            self.fields["valor"].disabled = True


class FiltroVipForm(forms.Form):
    """Só valida o que vem na URL (datas, ids); a consulta é montada na view."""
    CAMPOS_DATA = [("data_preparacao", "Data de preparação"), ("data_vip", "Data VIP"),
                   ("data_devolucao", "Data de devolução"), ("previsao_pagamento", "Previsão de pagamento")]
    ORDENS = [("-data_preparacao", "Preparação (mais recente)"), ("data_preparacao", "Preparação (mais antiga)"),
              ("data_devolucao", "Devolução (mais próxima)"), ("-data_devolucao", "Devolução (mais distante)"),
              ("placa", "Placa"), ("cliente__nome", "Cliente"), ("-valor", "Valor (maior)")]
    de = forms.DateField(required=False)
    ate = forms.DateField(required=False)
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.all(), required=False)
    servico = forms.ModelChoiceField(queryset=TipoServico.objects.all(), required=False)
    campo_data = forms.ChoiceField(choices=CAMPOS_DATA, required=False)
    ordem = forms.ChoiceField(choices=ORDENS, required=False)
