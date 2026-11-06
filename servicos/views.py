from django.urls import reverse_lazy

from cadastros.crud import CriarCrud, DetalheCrud, EditarCrud, ExcluirCrud, ListaCrud

from .forms import TipoServicoForm
from .models import TipoServico


class ServicoLista(ListaCrud):
    model = TipoServico
    template_name = "servicos/servico_lista.html"
    campos_busca = ["nome"]

    def get_queryset(self):
        qs = super().get_queryset()
        categoria = self.request.GET.get("categoria", "")
        if categoria in TipoServico.Categoria.values:
            qs = qs.filter(categoria=categoria)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categorias"] = TipoServico.Categoria.choices
        ctx["categoria_atual"] = self.request.GET.get("categoria", "")
        return ctx


class ServicoDetalhe(DetalheCrud):
    model = TipoServico
    template_name = "servicos/servico_detalhe.html"


# Criar/editar/excluir exigem as permissões add/change/delete,
# que só o grupo Administrador possui.
class ServicoCriar(CriarCrud):
    model = TipoServico
    form_class = TipoServicoForm
    extra_context = {"titulo": "Novo tipo de serviço", "url_voltar": reverse_lazy("servico_lista")}


class ServicoEditar(EditarCrud):
    model = TipoServico
    form_class = TipoServicoForm
    extra_context = {"titulo": "Editar tipo de serviço"}


class ServicoExcluir(ExcluirCrud):
    model = TipoServico
    success_url = reverse_lazy("servico_lista")
