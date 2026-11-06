from django.urls import path

from . import views

urlpatterns = [
    path("", views.Calendario.as_view(), name="agenda_calendario"),
    path("eventos/", views.EventosJson.as_view(), name="agenda_eventos"),
    path("pendencias/", views.Pendencias.as_view(), name="agenda_pendencias"),
    path("horario/", views.HorarioFuncionamentoEditar.as_view(), name="agenda_horario"),
    path("lista/", views.AgendamentoLista.as_view(), name="agendamento_lista"),
    path("novo/", views.AgendamentoCriar.as_view(), name="agendamento_novo"),
    path("<int:pk>/", views.AgendamentoDetalhe.as_view(), name="agendamento_detalhe"),
    path("<int:pk>/editar/", views.AgendamentoEditar.as_view(), name="agendamento_editar"),
    path("<int:pk>/excluir/", views.AgendamentoExcluir.as_view(), name="agendamento_excluir"),
    path("<int:pk>/status/<str:novo>/", views.AgendamentoStatus.as_view(), name="agendamento_status"),
    path("<int:pk>/concluir/", views.AgendamentoConcluir.as_view(), name="agendamento_concluir"),
    path("<int:pk>/remarcar/", views.AgendamentoRemarcar.as_view(), name="agendamento_remarcar"),
]
