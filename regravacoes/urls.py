from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.RegravacaoLista.as_view(), name="regravacao_lista"),
    path("nova/", v.RegravacaoCriar.as_view(), name="regravacao_novo"),
    path("veiculo/", v.RegravacaoVeiculoPorPlaca.as_view(), name="regravacao_veiculo"),
    path("empresa/", v.Empresa.as_view(), name="empresa"),
    path("<int:pk>/", v.RegravacaoDetalhe.as_view(), name="regravacao_detalhe"),
    path("<int:pk>/editar/", v.RegravacaoEditar.as_view(), name="regravacao_editar"),
    path("<int:pk>/excluir/", v.RegravacaoExcluir.as_view(), name="regravacao_excluir"),
    path("<int:pk>/concluir/", v.RegravacaoConcluir.as_view(), name="regravacao_concluir"),
    path("<int:pk>/reabrir/", v.RegravacaoReabrir.as_view(), name="regravacao_reabrir"),
    path("<int:pk>/cancelar/", v.RegravacaoCancelar.as_view(), name="regravacao_cancelar"),
    path("<int:pk>/documento/<str:tipo>/", v.DocumentoEmitir.as_view(), name="documento_emitir"),
    path("documentos/<int:pk>/", v.DocumentoBaixar.as_view(), name="documento_baixar"),
    path("anexo/<int:pk>/<str:tamanho>/", v.AnexoBaixar.as_view(), name="anexo_baixar"),

    path("parceiros/", v.ParceiroLista.as_view(), name="parceiro_lista"),
    path("parceiros/novo/", v.ParceiroCriar.as_view(), name="parceiro_novo"),
    path("parceiros/<int:pk>/", v.ParceiroDetalhe.as_view(), name="parceiro_detalhe"),
    path("parceiros/<int:pk>/editar/", v.ParceiroEditar.as_view(), name="parceiro_editar"),
    path("parceiros/<int:pk>/ativo/", v.ParceiroAtivo.as_view(), name="parceiro_ativo"),

    path("tecnicos/", v.TecnicoLista.as_view(), name="tecnico_lista"),
    path("tecnicos/novo/", v.TecnicoCriar.as_view(), name="tecnico_novo"),
    path("tecnicos/<int:pk>/editar/", v.TecnicoEditar.as_view(), name="tecnico_editar"),
    path("tecnicos/<int:pk>/ativo/", v.TecnicoAtivo.as_view(), name="tecnico_ativo"),
]
