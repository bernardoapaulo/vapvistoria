from django import forms
from django.db import transaction
from django.db.models import Q

from cadastros.models import Aluno, Cliente, Veiculo
from servicos.models import TipoServico

from financeiro import regras
from financeiro.dinheiro import reais

from . import historico
from .models import Atendimento

Status = Atendimento.Status


class _DataInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class SelectComDados(forms.Select):
    """Select que coloca atributos data-* em cada opção (usados pelo JavaScript do formulário)."""

    def __init__(self, *args, dados=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.dados = dados or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcao = super().create_option(name, value, label, selected, index, subindex, attrs)
        pk = getattr(value, "value", value)
        for chave, valor in self.dados.get(pk, {}).items():
            opcao["attrs"][f"data-{chave}"] = valor
        return opcao


class AtendimentoForm(forms.ModelForm):
    class Meta:
        model = Atendimento
        fields = [
            "cliente", "tipo_servico", "veiculo", "aluno", "data_atendimento", "status",
            "valor_cobrado", "desconto", "observacoes",
        ]
        widgets = {
            "data_atendimento": _DataInput(),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }
        error_messages = {
            "cliente": {"required": "Selecione o cliente."},
            "tipo_servico": {"required": "Selecione o tipo de serviço."},
            "data_atendimento": {"required": "Informe a data do atendimento.", "invalid": "Data inválida."},
            "valor_cobrado": {"invalid": "Informe um valor válido, por exemplo 150.00."},
            "desconto": {"invalid": "Informe um desconto válido, por exemplo 10.00."},
        }

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.pode_alterar_valor = usuario.has_perm("atendimentos.alterar_valor")
        pode_reabrir = usuario.has_perm("atendimentos.reabrir")
        atual = self.instance if self.instance.pk else None
        self._antes = historico.estado(atual) if atual else None
        self._tipo_antes = atual.tipo_servico_id if atual else None

        # Status oferecido: o atual + as transições permitidas.
        if atual:
            ids = [atual.status] + [
                s for s in Atendimento.TRANSICOES[atual.status]
                if pode_reabrir or atual.aberto  # sair de Concluído/Cancelado = reabrir
            ]
        else:
            ids = [Status.SOLICITADO, Status.AGENDADO, Status.EM_ANDAMENTO]
        self.fields["status"].choices = [(v, r) for v, r in Status.choices if v in ids]

        # Tipos de serviço: só os ativos (mais o atual, se já estiver inativo).
        tipos = TipoServico.objects.filter(Q(ativo=True) | Q(pk=self._tipo_antes))
        # (o widget é trocado ANTES de definir o queryset, para que as opções sejam ligadas a ele)
        self._com_dados("tipo_servico", tipos, {
            t.pk: {
                "exige": "aluno" if Atendimento.categoria_exige_aluno(t.categoria) else "veiculo",
                "valor": str(t.valor_padrao),
            } for t in tipos
        })
        self.fields["cliente"].empty_label = "Selecione o cliente"
        self.fields["tipo_servico"].empty_label = "Selecione o serviço"

        # Veículo e aluno: o JS esconde o que não pertence ao cliente/serviço escolhido.
        veiculos = Veiculo.objects.select_related("proprietario")
        self._com_dados("veiculo", veiculos, {v.pk: {"cliente": v.proprietario_id} for v in veiculos})
        alunos = Aluno.objects.all()
        self._com_dados("aluno", alunos, {a.pk: {"cliente": a.cliente_id or ""} for a in alunos})
        self.fields["veiculo"].empty_label = "Selecione o veículo"
        self.fields["aluno"].empty_label = "Selecione o aluno"
        self.fields["aluno"].help_text = "Se o aluno tiver um cliente vinculado, ele é sugerido automaticamente."

        # Funcionário não vê (nem altera) valor cobrado e desconto.
        self.fields["valor_cobrado"].required = False
        self.fields["desconto"].required = False
        if not self.pode_alterar_valor:
            # "disabled": o Django ignora o que vier no POST e mantém o valor atual,
            # então o funcionário não consegue alterar nem forjando a requisição.
            self.fields["valor_cobrado"].disabled = True
            self.fields["desconto"].disabled = True
        else:
            self.fields["valor_cobrado"].help_text = "Preenchido com o valor padrão do serviço; pode ser ajustado."

    def _com_dados(self, nome, queryset, dados):
        campo = self.fields[nome]
        campo.widget = SelectComDados(dados=dados)
        campo.queryset = queryset

    def clean(self):
        dados = super().clean()
        tipo = dados.get("tipo_servico")
        if tipo is None:
            return dados
        # Valor sai do tipo de serviço quando: o usuário não pode alterar valor (criação
        # ou troca de serviço) ou o campo foi deixado em branco na criação.
        trocou_tipo = self._tipo_antes != tipo.pk
        if not self.pode_alterar_valor:
            if self.instance.pk is None or trocou_tipo:
                dados["valor_cobrado"] = tipo.valor_padrao
                dados["desconto"] = Atendimento._meta.get_field("desconto").default
        elif dados.get("valor_cobrado") is None:
            dados["valor_cobrado"] = tipo.valor_padrao
        if dados.get("desconto") is None:
            dados["desconto"] = Atendimento._meta.get_field("desconto").default
        # O valor devido não pode ficar abaixo do que já foi recebido (estorne um recebimento antes).
        if self.instance.pk and dados.get("valor_cobrado") is not None:
            novo_final = dados["valor_cobrado"] - dados["desconto"]
            if novo_final < self.instance.valor_pago:
                self.add_error(None, (
                    f"Já foram recebidos {reais(self.instance.valor_pago)} deste atendimento; o valor final "
                    f"({reais(novo_final)}) não pode ficar abaixo disso. Estorne um recebimento antes de reduzir o valor."))
        return dados

    @transaction.atomic
    def save(self, commit=True):
        criando = self.instance.pk is None
        if criando:
            self.instance.registrado_por = self.usuario
        atendimento = super().save(commit)
        if criando:
            historico.registrar_criacao(atendimento, self.usuario)
        else:
            # Mudou o valor devido? A situação do pagamento (calculada) pode mudar junto.
            regras.recalcular_pagamento(atendimento)
            historico.registrar_mudancas(atendimento, self._antes, self.usuario)
        return atendimento


class FiltroAtendimentoForm(forms.Form):
    """Só para validar/limpar os filtros da listagem (GET)."""
    de = forms.DateField(required=False)
    ate = forms.DateField(required=False)
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.all(), required=False)
