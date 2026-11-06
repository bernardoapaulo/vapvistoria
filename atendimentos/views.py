from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View

from cadastros.crud import CriarCrud, DetalheCrud, EditarCrud, ExcluirCrud, ListaCrud
from cadastros.models import Aluno, Cliente, Veiculo
from financeiro.forms import RecebimentoForm
from servicos.models import TipoServico

from . import historico
from .forms import AtendimentoForm, FiltroAtendimentoForm
from .models import Atendimento

Status = Atendimento.Status

# Botões rápidos: status de destino -> (texto do botão, classe CSS, pede confirmação?)
ACOES_RAPIDAS = {
    Status.AGENDADO: ("Agendar", "btn--secundario", False),
    Status.EM_ANDAMENTO: ("Iniciar", "btn--secundario", False),
    Status.CONCLUIDO: ("Concluir", "", False),
    Status.CANCELADO: ("Cancelar", "btn--perigo", True),
}


class AtendimentoLista(ListaCrud):
    model = Atendimento
    template_name = "atendimentos/atendimento_lista.html"
    campos_busca = ["cliente__nome", "veiculo__placa", "aluno__nome", "tipo_servico__nome"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("cliente", "tipo_servico", "veiculo", "aluno")
        g = self.request.GET
        if g.get("status") in Status.values:
            qs = qs.filter(status=g["status"])
        if g.get("categoria") in dict(self._categorias()):
            qs = qs.filter(tipo_servico__categoria=g["categoria"])
        if g.get("pagamento") in Atendimento.SituacaoPagamento.values:
            qs = qs.filter(situacao_pagamento=g["pagamento"])
        if g.get("revisar") == "1":
            qs = qs.filter(revisar_pagamento=True)
        # Período e cliente passam por um formulário só para validar o que foi digitado.
        filtro = FiltroAtendimentoForm(g)
        if filtro.is_valid():
            c = filtro.cleaned_data
            if c["de"]:
                qs = qs.filter(data_atendimento__gte=c["de"])
            if c["ate"]:
                qs = qs.filter(data_atendimento__lte=c["ate"])
            if c["cliente"]:
                qs = qs.filter(cliente=c["cliente"])
        return qs

    @staticmethod
    def _categorias():
        return TipoServico.Categoria.choices

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        g = self.request.GET
        ctx.update({
            "status_opcoes": Status.choices,
            "categorias": self._categorias(),
            "pagamentos": Atendimento.SituacaoPagamento.choices,
            "clientes": Cliente.objects.only("id", "nome").order_by("nome"),
            "f": {k: g.get(k, "") for k in ("status", "categoria", "pagamento", "cliente", "de", "ate", "revisar")},
        })
        return ctx


class AtendimentoDetalhe(DetalheCrud):
    model = Atendimento
    template_name = "atendimentos/atendimento_detalhe.html"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "cliente", "tipo_servico", "veiculo", "aluno", "registrado_por")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        a, user = self.object, self.request.user
        pode_mudar = user.has_perm("atendimentos.change_atendimento")
        pode_reabrir = user.has_perm("atendimentos.reabrir")

        acoes = []
        if pode_mudar:
            for destino in Atendimento.TRANSICOES[a.status]:
                if a.fechado:  # sair de Concluído/Cancelado = reabrir
                    if pode_reabrir:
                        acoes.append({"status": destino.value, "rotulo": "Reabrir", "classe": "", "confirmar": ""})
                else:
                    rotulo, classe, confirma = ACOES_RAPIDAS[destino]
                    acoes.append({
                        "status": destino.value, "rotulo": rotulo, "classe": classe,
                        "confirmar": "Cancelar este atendimento?" if confirma else "",
                    })
        ctx.update({
            "historico": a.historico.select_related("usuario"),
            "acoes": acoes,
            # Recebimentos (app financeiro): quem tem `add_recebimento` registra; só o Administrador estorna/edita.
            "pode_receber": (
                user.has_perm("financeiro.add_recebimento") and a.status != Status.CANCELADO and a.valor_em_aberto > 0),
            "recebimento_form": RecebimentoForm(usuario=user, atendimento=a),
            "recebimentos": a.recebimentos.select_related("criado_por", "estornado_por").order_by("data", "id"),
            "pode_ver_financeiro": user.has_perm("financeiro.ver_financeiro"),
            "pode_estornar": user.has_perm("financeiro.estornar_recebimento"),
            "pode_editar": pode_mudar and (a.aberto or pode_reabrir),
            # Agenda deste atendimento (related_name "agendamentos", do app agenda)
            "agendamentos": a.agendamentos.com_detalhes().order_by("inicio"),
            "pode_agendar": a.aberto and user.has_perm("agenda.add_agendamento"),
        })
        return ctx


class _FormularioAtendimentoMixin:
    """Entrega o usuário ao formulário (ele decide o que mostrar e grava no histórico)."""
    form_class = AtendimentoForm
    template_name = "atendimentos/atendimento_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs


class AtendimentoCriar(_FormularioAtendimentoMixin, CriarCrud):
    model = Atendimento
    extra_context = {"titulo": "Novo atendimento", "url_voltar": reverse_lazy("atendimento_lista")}

    def get_initial(self):
        # Atalhos: /atendimentos/novo/?cliente=ID, ?veiculo=ID ou ?aluno=ID
        inicial = super().get_initial()
        g = self.request.GET
        if g.get("veiculo", "").isdigit():
            veiculo = Veiculo.objects.filter(pk=g["veiculo"]).first()
            if veiculo:
                inicial.update(veiculo=veiculo.pk, cliente=veiculo.proprietario_id)
        if g.get("aluno", "").isdigit():
            aluno = Aluno.objects.filter(pk=g["aluno"]).first()
            if aluno:
                inicial["aluno"] = aluno.pk
                if aluno.cliente_id:
                    inicial["cliente"] = aluno.cliente_id
        if g.get("cliente", "").isdigit():
            inicial["cliente"] = g["cliente"]
        return inicial

    def get_success_url(self):
        # Vindo do formulário de agendamento ("criar atendimento novo"): volta para agendar.
        if self.request.GET.get("agendar") and self.request.user.has_perm("agenda.add_agendamento"):
            return f"{reverse('agendamento_novo')}?atendimento={self.object.pk}"
        return super().get_success_url()


class AtendimentoEditar(_FormularioAtendimentoMixin, EditarCrud):
    model = Atendimento
    extra_context = {"titulo": "Editar atendimento"}

    def get_object(self, queryset=None):
        a = super().get_object(queryset)
        # Concluído/Cancelado: só quem pode reabrir (Administrador) edita.
        if a.fechado and not self.request.user.has_perm("atendimentos.reabrir"):
            raise PermissionDenied("Atendimento concluído ou cancelado só pode ser alterado por um administrador.")
        return a


class AtendimentoExcluir(ExcluirCrud):
    model = Atendimento
    success_url = reverse_lazy("atendimento_lista")


class AtendimentoStatus(PermissionRequiredMixin, View):
    """Botões rápidos (Iniciar, Concluir, Cancelar, Reabrir...). Só aceita POST."""
    permission_required = "atendimentos.change_atendimento"
    http_method_names = ["post"]

    def post(self, request, pk, novo):
        a = get_object_or_404(Atendimento, pk=pk)
        if novo not in Status.values or not a.pode_ir_para(novo):
            messages.error(request, "Esta mudança de status não é permitida para este atendimento.")
        else:
            if a.fechado and not request.user.has_perm("atendimentos.reabrir"):
                raise PermissionDenied("Somente um administrador pode reabrir um atendimento.")
            historico.alterar_status(a, novo, request.user)
            messages.success(request, f"Status alterado para {a.get_status_display()}.")
            if novo == Status.CANCELADO and a.valor_pago > 0:
                messages.warning(request, (
                    "Este atendimento já recebeu dinheiro. O valor continua no caixa até um administrador "
                    "estornar o recebimento."))
        return redirect(a)


class AtendimentoReceber(PermissionRequiredMixin, View):
    """Botão "Registrar recebimento" (também para Funcionário). Só aceita POST; a regra está em financeiro.regras."""
    permission_required = "financeiro.add_recebimento"
    http_method_names = ["post"]

    def post(self, request, pk):
        a = get_object_or_404(Atendimento, pk=pk)
        form = RecebimentoForm(request.POST, usuario=request.user, atendimento=a)
        if form.is_valid() and form.salvar():
            messages.success(request, "Recebimento registrado.")
        else:
            for erros in form.errors.values():
                messages.error(request, erros[0])
        voltar = request.POST.get("voltar", "")
        return redirect(voltar if voltar.startswith("/financeiro/") else a)  # "Contas a receber" volta para a lista
