from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("contas.urls")),
    path("clientes/", include("cadastros.urls_clientes")),
    path("alunos/", include("cadastros.urls_alunos")),
    path("veiculos/", include("cadastros.urls_veiculos")),
    path("servicos/", include("servicos.urls")),
    path("atendimentos/", include("atendimentos.urls")),
    path("agenda/", include("agenda.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("financeiro/", include("financeiro.urls")),
]
