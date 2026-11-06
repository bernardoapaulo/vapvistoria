from django.urls import path

from . import views
from .crud import rotas_crud

urlpatterns = rotas_crud(
    "aluno", views.AlunoLista, views.AlunoDetalhe,
    views.AlunoCriar, views.AlunoEditar, views.AlunoExcluir,
) + [
    path("<int:pk>/documento/<str:campo>/", views.AlunoDocumento.as_view(), name="aluno_documento"),
]
