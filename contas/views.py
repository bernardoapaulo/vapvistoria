from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from agenda.consultas import contar_pendencias
from agenda.models import Agendamento
from atendimentos.models import Atendimento
from cadastros.models import Aluno, Cliente, Veiculo
from dashboard.services import resumo_do_mes
from financeiro.services import resumo_do_mes as resumo_financeiro_do_mes
from servicos.models import TipoServico


class InicioView(LoginRequiredMixin, TemplateView):
    """Página inicial simples com contadores. Será enriquecida nas próximas etapas."""
    template_name = "inicio.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_clientes"] = Cliente.objects.count()
        ctx["total_alunos"] = Aluno.objects.count()
        ctx["total_veiculos"] = Veiculo.objects.count()
        ctx["total_servicos"] = TipoServico.objects.filter(ativo=True).count()
        ctx["total_em_aberto"] = Atendimento.objects.em_aberto().count()
        ctx["recentes"] = Atendimento.objects.select_related("cliente", "tipo_servico")[:5]
        if self.request.user.has_perm("atendimentos.view_atendimento"):
            ctx["resumo_mes"] = resumo_do_mes(com_valores=self.request.user.has_perm("atendimentos.ver_faturamento"))
        if self.request.user.has_perm("financeiro.ver_financeiro"):
            ctx["resumo_financeiro"] = resumo_financeiro_do_mes()
        if self.request.user.has_perm("agenda.view_agendamento"):
            ctx["agenda_hoje"] = Agendamento.objects.com_detalhes().hoje()
            ctx["total_pendencias"] = contar_pendencias()
        return ctx
