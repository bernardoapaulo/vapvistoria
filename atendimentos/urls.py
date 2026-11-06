from django.urls import path

from cadastros.crud import rotas_crud

from . import views

urlpatterns = rotas_crud(
    "atendimento", views.AtendimentoLista, views.AtendimentoDetalhe,
    views.AtendimentoCriar, views.AtendimentoEditar, views.AtendimentoExcluir,
) + [
    path("<int:pk>/status/<str:novo>/", views.AtendimentoStatus.as_view(), name="atendimento_status"),
    path("<int:pk>/receber/", views.AtendimentoReceber.as_view(), name="atendimento_receber"),
]
