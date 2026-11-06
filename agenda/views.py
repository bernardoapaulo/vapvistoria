from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.forms import modelformset_factory
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View
from django.views.generic import TemplateView

from atendimentos import historico
from atendimentos.models import Atendimento
from cadastros.crud import CriarCrud, DetalheCrud, EditarCrud, ExcluirCrud, ListaCrud
from servicos.models import TipoServico

from . import consultas, regras
from .forms import AgendamentoForm, FiltroAgendamentoForm, RemarcarForm, usuarios_ativos
from .models import Agendamento, HorarioFuncionamento, limites_do_dia

Status = Agendamento.Status

# Botões rápidos: status de destino -> (texto, classe CSS, pergunta de confirmação)
ACOES_RAPIDAS = {
    Status.CONFIRMADO: ("Confirmar", "btn--secundario", ""),
    Status.EM_ANDAMENTO: ("Iniciar", "btn--secundario", ""),
    Status.CONCLUIDO: ("Concluir", "", ""),
    Status.CANCELADO: ("Cancelar", "btn--perigo", "Cancelar este agendamento?"),
    Status.NAO_COMPARECEU: ("Não compareceu", "btn--perigo", "Marcar como “não compareceu”?"),
    Status.AGENDADO: ("Reabrir", "", ""),
}


def _checar_edicao(request, ag):
    """Cancelado / Não compareceu / Remarcado só mudam com o Administrador."""
    if ag.travado and not request.user.has_perm("agenda.reabrir"):
        raise PermissionDenied("Este agendamento só pode ser alterado por um administrador.")


# ---------- Calendário ----------
class Calendario(PermissionRequiredMixin, TemplateView):
    permission_required = "agenda.view_agendamento"
    template_name = "agenda/calendario.html"


class EventosJson(PermissionRequiredMixin, View):
    """
    Alimenta o calendário. LGPD: só vai o necessário (serviço, cliente, horário e
    status) - nada de telefone, CPF ou endereço.
    """
    permission_required = "agenda.view_agendamento"

    def get(self, request):
        ini = parse_datetime(request.GET.get("start", ""))
        fim = parse_datetime(request.GET.get("end", ""))
        qs = Agendamento.objects.com_detalhes()
        if ini and fim:
            qs = qs.filter(inicio__lt=fim, fim__gt=ini)
        else:  # sem período válido: janela de 60 dias ao redor de hoje
            agora = timezone.now()
            qs = qs.filter(inicio__gte=agora - timedelta(days=30), inicio__lt=agora + timedelta(days=30))
        eventos = []
        for g in qs:
            classes = [f"evento-status-{g.status}"] + (["evento-atrasado"] if g.atrasado else [])
            # Hora local SEM fuso: o calendário mostra exatamente o horário da empresa.
            eventos.append({
                "id": g.pk,
                "title": f"{g.atendimento.tipo_servico.nome} · {g.atendimento.cliente.nome}",
                "start": timezone.localtime(g.inicio).replace(tzinfo=None).isoformat(),
                "end": timezone.localtime(g.fim).replace(tzinfo=None).isoformat(),
                "url": g.get_absolute_url(),
                "classNames": classes,
            })
        return JsonResponse(eventos, safe=False)


# ---------- Lista e CRUD ----------
class AgendamentoLista(ListaCrud):
    model = Agendamento
    template_name = "agenda/agendamento_lista.html"
    campos_busca = [
        "atendimento__cliente__nome", "atendimento__tipo_servico__nome",
        "atendimento__veiculo__placa", "atendimento__aluno__nome", "detalhe_local",
    ]

    def get_queryset(self):
        qs = super().get_queryset().com_detalhes().order_by("-inicio", "-id")
        g = self.request.GET
        if g.get("status") in Status.values:
            qs = qs.filter(status=g["status"])
        if g.get("categoria") in TipoServico.Categoria.values:
            qs = qs.filter(atendimento__tipo_servico__categoria=g["categoria"])
        if g.get("local") in Agendamento.Local.values:
            qs = qs.filter(local=g["local"])
        filtro = FiltroAgendamentoForm(g)
        if filtro.is_valid():
            c = filtro.cleaned_data
            if c["de"]:
                qs = qs.filter(inicio__gte=limites_do_dia(c["de"])[0])
            if c["ate"]:
                qs = qs.filter(inicio__lt=limites_do_dia(c["ate"])[1])
            if c["responsavel"]:
                qs = qs.filter(responsavel=c["responsavel"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        g = self.request.GET
        ctx.update({
            "status_opcoes": Status.choices,
            "categorias": TipoServico.Categoria.choices,
            "locais": Agendamento.Local.choices,
            "responsaveis": usuarios_ativos(),
            "agendamentos": ctx["object_list"],
            "f": {k: g.get(k, "") for k in ("status", "categoria", "local", "responsavel", "de", "ate")},
        })
        return ctx


class AgendamentoDetalhe(DetalheCrud):
    model = Agendamento
    template_name = "agenda/agendamento_detalhe.html"

    def get_queryset(self):
        return super().get_queryset().com_detalhes().select_related("remarcado_de", "criado_por")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ag, user = self.object, self.request.user
        pode_mudar = user.has_perm("agenda.change_agendamento")
        pode_reabrir = user.has_perm("agenda.reabrir")

        acoes = []
        if pode_mudar:
            for destino in Agendamento.TRANSICOES[ag.status]:
                if ag.travado and not pode_reabrir:
                    continue
                rotulo, classe, pergunta = ACOES_RAPIDAS[destino]
                acoes.append({
                    "status": destino.value, "rotulo": rotulo, "classe": classe, "confirmar": pergunta,
                    "link": reverse("agendamento_concluir", args=[ag.pk]) if destino == Status.CONCLUIDO else "",
                })
        ctx.update({
            "acoes": acoes,
            "pode_remarcar": pode_mudar and ag.status in Agendamento.PODE_REMARCAR,
            "pode_editar": pode_mudar and (not ag.travado or pode_reabrir),
            "conflitos": ag.conflitos() if ag.ativo else [],
            "remarcacoes": ag.remarcacoes.com_detalhes(),
        })
        return ctx


class AgendamentoCriar(CriarCrud):
    model = Agendamento
    form_class = AgendamentoForm
    template_name = "agenda/agendamento_form.html"
    extra_context = {"titulo": "Novo agendamento", "url_voltar": reverse_lazy("agenda_calendario")}
    mensagem_sucesso = "Agendamento criado com sucesso."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs

    def get_initial(self):
        inicial = super().get_initial()
        g = self.request.GET
        if g.get("atendimento", "").isdigit():  # /agenda/novo/?atendimento=ID
            inicial["atendimento"] = g["atendimento"]
        if g.get("inicio"):  # ?inicio=2026-10-30T09:00 (clique no calendário, se existir)
            inicial["inicio"] = g["inicio"]
        return inicial


class AgendamentoEditar(EditarCrud):
    model = Agendamento
    form_class = AgendamentoForm
    template_name = "agenda/agendamento_form.html"
    extra_context = {"titulo": "Editar agendamento"}
    mensagem_sucesso = "Agendamento atualizado com sucesso."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs

    def get_object(self, queryset=None):
        ag = super().get_object(queryset)
        _checar_edicao(self.request, ag)
        return ag


class AgendamentoExcluir(ExcluirCrud):
    model = Agendamento
    success_url = reverse_lazy("agendamento_lista")

    def form_valid(self, form):
        ag = self.object
        atendimento, texto = ag.atendimento, f"Agendamento de {regras.quando(ag)} excluído"
        resposta = super().form_valid(form)
        historico.registrar_agenda(atendimento, texto, self.request.user)
        return resposta


# ---------- Botões rápidos ----------
class AgendamentoStatus(PermissionRequiredMixin, View):
    permission_required = "agenda.change_agendamento"
    http_method_names = ["post"]

    def post(self, request, pk, novo):
        ag = get_object_or_404(Agendamento.objects.select_related("atendimento"), pk=pk)
        _checar_edicao(request, ag)
        if novo == Status.CONCLUIDO:  # concluir tem uma pergunta própria
            return redirect("agendamento_concluir", pk=ag.pk)
        try:
            regras.mudar_status(ag, novo, request.user)
            messages.success(request, f"Agendamento: {ag.get_status_display()}.")
        except regras.RegraAgenda as erro:
            messages.error(request, str(erro))
        return redirect(ag)


class AgendamentoConcluir(PermissionRequiredMixin, View):
    """Conclui o agendamento e pergunta se o atendimento também deve ser concluído."""
    permission_required = "agenda.change_agendamento"

    def _contexto(self, request, ag):
        at = ag.atendimento
        pode = (
            at.status == Atendimento.Status.EM_ANDAMENTO
            and request.user.has_perm("atendimentos.change_atendimento")
        )
        outros = regras.outros_ativos(ag)
        return {"object": ag, "pode_concluir_atendimento": pode, "outros_ativos": outros,
                "marcado": pode and outros == 0}

    def get(self, request, pk):
        ag = get_object_or_404(Agendamento.objects.com_detalhes(), pk=pk)
        _checar_edicao(request, ag)
        if not ag.pode_ir_para(Status.CONCLUIDO):
            messages.error(request, "Só é possível concluir um agendamento que está em andamento.")
            return redirect(ag)
        return render(request, "agenda/agendamento_concluir.html", self._contexto(request, ag))

    def post(self, request, pk):
        ag = get_object_or_404(Agendamento.objects.com_detalhes(), pk=pk)
        _checar_edicao(request, ag)
        concluir = request.POST.get("concluir_atendimento") == "on" and self._contexto(request, ag)["pode_concluir_atendimento"]
        try:
            regras.mudar_status(ag, Status.CONCLUIDO, request.user, concluir_atendimento=concluir)
        except regras.RegraAgenda as erro:
            messages.error(request, str(erro))
            return redirect(ag)
        messages.success(request, "Agendamento concluído" + (" e atendimento concluído." if concluir else "."))
        return redirect(ag)


class AgendamentoRemarcar(PermissionRequiredMixin, View):
    permission_required = "agenda.change_agendamento"
    template_name = "agenda/agendamento_remarcar.html"

    def _obter(self, request, pk):
        ag = get_object_or_404(Agendamento.objects.com_detalhes(), pk=pk)
        _checar_edicao(request, ag)
        return ag

    def get(self, request, pk):
        ag = self._obter(request, pk)
        if ag.status not in Agendamento.PODE_REMARCAR:
            messages.error(request, "Só é possível remarcar um agendamento Agendado ou Confirmado.")
            return redirect(ag)
        form = RemarcarForm(agendamento=ag, initial={"inicio": ag.inicio, "fim": ag.fim})
        return render(request, self.template_name, {"object": ag, "form": form})

    def post(self, request, pk):
        ag = self._obter(request, pk)
        form = RemarcarForm(request.POST, agendamento=ag)
        if form.is_valid():
            try:
                novo = regras.remarcar(ag, form.cleaned_data["inicio"], form.cleaned_data["fim"], request.user)
            except regras.RegraAgenda as erro:
                messages.error(request, str(erro))
                return redirect(ag)
            messages.success(request, "Agendamento remarcado. O anterior ficou como “Remarcado”.")
            return redirect(novo)
        return render(request, self.template_name, {"object": ag, "form": form})


# ---------- Pendências e horário ----------
class Pendencias(PermissionRequiredMixin, TemplateView):
    permission_required = "agenda.view_agendamento"
    template_name = "agenda/pendencias.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(consultas.pendencias())
        return ctx


HorarioFormSet = modelformset_factory(
    HorarioFuncionamento, fields=("aberto", "abre", "fecha"), extra=0, edit_only=True,
)


class HorarioFuncionamentoEditar(PermissionRequiredMixin, View):
    """Tela do Administrador: uma linha por dia da semana."""
    permission_required = "agenda.change_horariofuncionamento"
    template_name = "agenda/horario_form.html"

    def get(self, request):
        return render(request, self.template_name, {"formset": self._formset()})

    def post(self, request):
        formset = self._formset(request.POST)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Horário de funcionamento salvo.")
            return redirect("agenda_horario")
        messages.error(request, "Não foi possível salvar. Corrija os campos destacados.")
        return render(request, self.template_name, {"formset": formset})

    @staticmethod
    def _formset(dados=None):
        return HorarioFormSet(dados, queryset=HorarioFuncionamento.objects.order_by("dia_semana"))
