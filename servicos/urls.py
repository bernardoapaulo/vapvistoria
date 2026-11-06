from cadastros.crud import rotas_crud

from . import views

urlpatterns = rotas_crud(
    "servico", views.ServicoLista, views.ServicoDetalhe,
    views.ServicoCriar, views.ServicoEditar, views.ServicoExcluir,
)
