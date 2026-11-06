from . import views
from .crud import rotas_crud

urlpatterns = rotas_crud(
    "veiculo", views.VeiculoLista, views.VeiculoDetalhe,
    views.VeiculoCriar, views.VeiculoEditar, views.VeiculoExcluir,
)
