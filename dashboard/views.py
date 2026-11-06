from django.contrib.auth.mixins import PermissionRequiredMixin
from django.views import View
from django.views.generic import TemplateView

from servicos.models import TipoServico

from . import graficos, services
from .exportacao import numero_br, resposta_csv, texto_seguro
from .forms import FiltroDashboardForm


class DashboardView(PermissionRequiredMixin, TemplateView):
    """
    Dashboard de desempenho. A parte financeira (valores em R$) só é calculada e enviada
    ao template para quem tem `atendimentos.ver_faturamento`: para os demais a chave
    "financeiro" simplesmente não existe no contexto.
    """
    permission_required = "atendimentos.view_atendimento"
    template_name = "dashboard/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = FiltroDashboardForm(self.request.GET or None)
        f = form.filtros()
        painel = services.painel_operacional(f)

        ind, comp = painel["indicadores"], painel["comparativo"]
        categorias = [
            {"rotulo": rotulo, "valor": ind["por_categoria"][chave], "variacao": comp["por_categoria"][chave]}
            for chave, rotulo in TipoServico.Categoria.choices
        ]
        ctx.update({
            "form": form,
            "periodo": f.periodo,
            "indicadores": ind,
            "comparativo": comp,
            "categorias": categorias,
            "situacao": painel["situacao"],
            "ranking": painel["ranking"],
            "por_responsavel": painel["por_responsavel"],
            "abertos_antigos": painel["abertos_antigos"],
            "graficos": {
                "mensal": graficos.mensal(painel["mensal"], "Serviços realizados"),
                "status": graficos.status(painel["status"]),
                "ranking": graficos.ranking(painel["ranking"]),
                "dias": graficos.barras_simples(painel["agenda"]["dias"], "Agendamentos"),
                "horas": graficos.barras_simples(painel["agenda"]["horas"], "Agendamentos"),
            },
            "querystring": self.request.GET.urlencode(),
        })

        if self.request.user.has_perm("atendimentos.ver_faturamento"):
            fin = services.painel_financeiro(f)
            fin["graficos"] = {
                "mensal": graficos.mensal(fin["mensal"], "Faturamento (R$)", formato="moeda"),
                "categorias": graficos.por_categoria(fin["por_categoria"], formato="moeda"),
                "pagamentos": graficos.pagamentos(fin["pagamentos"]),
            }
            ctx["financeiro"] = fin
        return ctx


class ExportarCsv(PermissionRequiredMixin, View):
    """CSV dos serviços realizados no período (mesmos filtros da tela). Só Administrador."""
    permission_required = "atendimentos.exportar_dados"

    def get(self, request):
        f = FiltroDashboardForm(request.GET or None).filtros()
        resposta, w = resposta_csv(f"servicos_{f.periodo.inicio:%Y-%m-%d}_a_{f.periodo.fim:%Y-%m-%d}.csv")
        w.writerow(["Data", "Cliente", "Serviço", "Categoria", "Valor cobrado", "Desconto",
                    "Valor final", "Situação do pagamento", "Valor pago", "Forma de pagamento"])
        for a in services.linhas_para_exportar(f):
            formas = ", ".join(dict.fromkeys(r.get_forma_display() for r in a.recebimentos_validos))
            w.writerow([
                f"{a.data_atendimento:%d/%m/%Y}", texto_seguro(a.cliente.nome), texto_seguro(a.tipo_servico.nome),
                a.tipo_servico.get_categoria_display(), numero_br(a.valor_cobrado), numero_br(a.desconto),
                numero_br(a.valor_final), a.get_situacao_pagamento_display(), numero_br(a.valor_pago), formas,
            ])
        return resposta
