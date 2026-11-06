"""
Views genéricas de CRUD reaproveitadas por Clientes, Alunos, Veículos e
Tipos de serviço. Cada cadastro só precisa informar o modelo, o formulário,
os campos de busca e os templates.

Segurança: todas as views exigem login e a permissão nativa do Django
correspondente (view/add/change/delete). Quem não está logado vai para a tela
de login; quem está logado mas sem permissão recebe erro 403.
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import ProtectedError, Q
from django.urls import path
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView


class PermissaoCrudMixin(PermissionRequiredMixin):
    """Deriva a permissão (ex.: cadastros.add_cliente) da ação e do modelo."""
    acao = "view"

    def get_permission_required(self):
        m = self.model._meta
        return [f"{m.app_label}.{self.acao}_{m.model_name}"]


class ListaCrud(PermissaoCrudMixin, ListView):
    acao = "view"
    campos_busca = []          # campos usados pelo filtro ?q=
    paginate_by = settings.ITENS_POR_PAGINA

    def get_queryset(self):
        qs = super().get_queryset()
        self.termo = self.request.GET.get("q", "").strip()
        if self.termo and self.campos_busca:
            filtro = Q()
            for campo in self.campos_busca:
                filtro |= Q(**{f"{campo}__icontains": self.termo})
            qs = qs.filter(filtro)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["termo"] = self.termo
        # Filtros atuais (sem "page"), para a paginação preservá-los nos links.
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        ctx["querystring"] = parametros.urlencode()
        return ctx


class DetalheCrud(PermissaoCrudMixin, DetailView):
    acao = "view"


class _MensagemFormMixin:
    mensagem_sucesso = "Registro salvo com sucesso."

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, self.mensagem_sucesso)
        return resposta

    def form_invalid(self, form):
        messages.error(self.request, "Não foi possível salvar. Corrija os campos destacados.")
        return super().form_invalid(form)


class CriarCrud(PermissaoCrudMixin, _MensagemFormMixin, CreateView):
    acao = "add"
    template_name = "form_generico.html"
    mensagem_sucesso = "Cadastro criado com sucesso."


class EditarCrud(PermissaoCrudMixin, _MensagemFormMixin, UpdateView):
    acao = "change"
    template_name = "form_generico.html"
    mensagem_sucesso = "Alterações salvas com sucesso."


class ExcluirCrud(PermissaoCrudMixin, DeleteView):
    acao = "delete"
    template_name = "confirmar_exclusao.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["nome_modelo"] = self.model._meta.verbose_name
        return ctx

    def form_valid(self, form):
        try:
            resposta = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                "Este cadastro não pode ser excluído porque está vinculado a outros registros "
                "(por exemplo, um cliente com veículos). Remova os vínculos antes.",
            )
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(self.request, "Registro excluído com sucesso.")
        return resposta


def rotas_crud(prefixo, lista, detalhe, criar, editar, excluir):
    """Gera as 5 rotas padrão: lista, novo, detalhe, editar, excluir."""
    return [
        path("", lista.as_view(), name=f"{prefixo}_lista"),
        path("novo/", criar.as_view(), name=f"{prefixo}_novo"),
        path("<int:pk>/", detalhe.as_view(), name=f"{prefixo}_detalhe"),
        path("<int:pk>/editar/", editar.as_view(), name=f"{prefixo}_editar"),
        path("<int:pk>/excluir/", excluir.as_view(), name=f"{prefixo}_excluir"),
    ]
