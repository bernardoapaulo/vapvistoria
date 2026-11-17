from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.VipLista.as_view(), name="vip_lista"),
    path("novo/", v.VipCriar.as_view(), name="vip_novo"),
    path("veiculo/", v.VipVeiculoPorPlaca.as_view(), name="vip_veiculo"),
    path("foto/<int:pk>/<str:tamanho>/", v.VipFoto.as_view(), name="vip_foto"),
    path("<int:pk>/", v.VipDetalhe.as_view(), name="vip_detalhe"),
    path("<int:pk>/editar/", v.VipEditar.as_view(), name="vip_editar"),
    path("<int:pk>/excluir/", v.VipExcluir.as_view(), name="vip_excluir"),
    path("<int:pk>/concluir/", v.VipConcluir.as_view(), name="vip_concluir"),
    path("<int:pk>/reabrir/", v.VipReabrir.as_view(), name="vip_reabrir"),
]
