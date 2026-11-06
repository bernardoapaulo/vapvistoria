from . import views
from .crud import rotas_crud

urlpatterns = rotas_crud(
    "cliente", views.ClienteLista, views.ClienteDetalhe,
    views.ClienteCriar, views.ClienteEditar, views.ClienteExcluir,
)
