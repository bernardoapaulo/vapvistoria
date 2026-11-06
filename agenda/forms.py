from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from atendimentos.models import Atendimento

from . import regras
from .models import Agendamento, HorarioFuncionamento


class _DataHoraInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M", **kwargs)


class _UsuarioChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, usuario):
        return usuario.get_full_name() or usuario.get_username()


def usuarios_ativos():
    return get_user_model().objects.filter(is_active=True).order_by("username")


class AvisosMixin:
    """
    Conflito de horário e horário fora do expediente são AVISOS, não erros:
    o formulário volta mostrando o aviso e só salva quando o usuário marca
    "Salvar mesmo assim" (campo confirmar_conflito).
    """
    confirmar_conflito = forms.BooleanField(required=False, label="Salvar mesmo assim")
    conflitos = ()
    aviso_expediente = ""

    @property
    def tem_avisos(self):
        return bool(self.conflitos or self.aviso_expediente)

    def verificar_avisos(self, provisorio):
        """`provisorio` é um Agendamento ainda não salvo, só para consultar os conflitos."""
        self.conflitos = list(provisorio.conflitos())
        self.aviso_expediente = HorarioFuncionamento.aviso_para(provisorio.inicio, provisorio.fim)
        if self.tem_avisos and not self.cleaned_data.get("confirmar_conflito"):
            raise ValidationError(
                "Há avisos para este horário. Confira abaixo e marque “Salvar mesmo assim” para continuar."
            )


class AgendamentoForm(AvisosMixin, forms.ModelForm):
    confirmar_conflito = AvisosMixin.confirmar_conflito

    class Meta:
        model = Agendamento
        fields = ["atendimento", "inicio", "fim", "local", "detalhe_local", "responsavel", "observacoes"]
        widgets = {
            "inicio": _DataHoraInput(),
            "fim": _DataHoraInput(),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }
        error_messages = {
            "atendimento": {"required": "Selecione o atendimento."},
            "inicio": {"required": "Informe o início.", "invalid": "Data e hora de início inválidas."},
            "fim": {"invalid": "Data e hora de fim inválidas."},
        }

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self._antes = (self.instance.inicio, self.instance.fim) if self.instance.pk else None

        # Só atendimentos em aberto (mais o atual, na edição).
        atual = self.instance.atendimento_id
        self.fields["atendimento"].queryset = (
            Atendimento.objects.filter(Q(status__in=Atendimento.STATUS_ABERTOS) | Q(pk=atual))
            .select_related("cliente", "tipo_servico", "veiculo", "aluno").order_by("-id")
        )
        self.fields["atendimento"].label_from_instance = self._rotulo_atendimento
        self.fields["atendimento"].empty_label = "Selecione o atendimento"
        self.fields["fim"].required = False
        self.fields["fim"].help_text = "Se ficar em branco, será 1 hora depois do início."
        self.fields["responsavel"] = _UsuarioChoiceField(
            queryset=usuarios_ativos(), required=False, label="Responsável", empty_label="Sem responsável",
        )

    @staticmethod
    def _rotulo_atendimento(a):
        referente = a.veiculo.placa if a.veiculo else (a.aluno.nome if a.aluno else "")
        return f"#{a.pk} · {a.cliente.nome} — {a.tipo_servico.nome}" + (f" ({referente})" if referente else "")

    def clean(self):
        dados = super().clean()
        inicio = dados.get("inicio")
        if inicio and not dados.get("fim"):
            dados["fim"] = inicio + timedelta(hours=1)
        fim = dados.get("fim")
        if inicio and fim and fim > inicio:
            provisorio = Agendamento(
                pk=self.instance.pk, inicio=inicio, fim=fim, local=dados.get("local"),
                responsavel=dados.get("responsavel"), status=self.instance.status,
            )
            self.verificar_avisos(provisorio)
        return dados

    @transaction.atomic
    def save(self, commit=True):
        criando = self.instance.pk is None
        if criando:
            self.instance.criado_por = self.usuario
        ag = super().save(commit)
        if criando:
            regras.apos_criar(ag, self.usuario)
        else:
            regras.apos_editar(ag, *self._antes, self.usuario)
        return ag


class RemarcarForm(AvisosMixin, forms.Form):
    inicio = forms.DateTimeField(
        label="Novo início", widget=_DataHoraInput(),
        error_messages={"required": "Informe o novo início.", "invalid": "Data e hora inválidas."},
    )
    fim = forms.DateTimeField(
        label="Novo fim", required=False, widget=_DataHoraInput(),
        help_text="Se ficar em branco, será 1 hora depois do início.",
        error_messages={"invalid": "Data e hora inválidas."},
    )
    confirmar_conflito = AvisosMixin.confirmar_conflito

    def __init__(self, *args, agendamento, **kwargs):
        super().__init__(*args, **kwargs)
        self.agendamento = agendamento

    def clean(self):
        dados = super().clean()
        inicio = dados.get("inicio")
        if inicio and not dados.get("fim"):
            dados["fim"] = inicio + timedelta(hours=1)
        fim = dados.get("fim")
        if inicio and fim:
            if fim <= inicio:
                self.add_error("fim", "O horário de fim deve ser posterior ao horário de início.")
            else:
                ag = self.agendamento
                # pk igual ao do antigo: ele não conta como conflito (vai virar "Remarcado").
                self.verificar_avisos(Agendamento(
                    pk=ag.pk, inicio=inicio, fim=fim, local=ag.local,
                    responsavel=ag.responsavel, status=Agendamento.Status.AGENDADO,
                ))
        return dados


class FiltroAgendamentoForm(forms.Form):
    """Só valida/limpa os filtros da listagem (GET)."""
    de = forms.DateField(required=False)
    ate = forms.DateField(required=False)
    responsavel = forms.ModelChoiceField(queryset=get_user_model().objects.all(), required=False)
