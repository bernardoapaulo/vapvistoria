from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.FinanceiroDashboard.as_view(), name="financeiro"),
    path("receber/", v.ContasReceber.as_view(), name="contas_receber"),
    path("pagar/", v.ContasPagar.as_view(), name="contas_pagar"),
    path("fluxo/", v.FluxoCaixa.as_view(), name="fluxo_caixa"),

    # Recebimentos (nunca excluídos: só estornados)
    path("recebimentos/", v.RecebimentoLista.as_view(), name="recebimento_lista"),
    path("recebimentos/novo/", v.RecebimentoCriar.as_view(), name="recebimento_novo"),
    path("recebimentos/<int:pk>/", v.RecebimentoDetalhe.as_view(), name="recebimento_detalhe"),
    path("recebimentos/<int:pk>/editar/", v.RecebimentoEditar.as_view(), name="recebimento_editar"),
    path("recebimentos/<int:pk>/estornar/", v.RecebimentoEstornar.as_view(), name="recebimento_estornar"),

    # Despesas
    path("despesas/", v.DespesaLista.as_view(), name="despesa_lista"),
    path("despesas/nova/", v.DespesaCriar.as_view(), name="despesa_novo"),
    path("despesas/<int:pk>/", v.DespesaDetalhe.as_view(), name="despesa_detalhe"),
    path("despesas/<int:pk>/editar/", v.DespesaEditar.as_view(), name="despesa_editar"),
    path("despesas/<int:pk>/excluir/", v.DespesaExcluir.as_view(), name="despesa_excluir"),
    path("despesas/<int:pk>/pagar/", v.DespesaPagar.as_view(), name="despesa_pagar"),
    path("despesas/<int:pk>/comprovante/", v.DespesaComprovante.as_view(), name="despesa_comprovante"),

    path("categorias/", v.CategoriaLista.as_view(), name="categoria_despesa_lista"),
    path("categorias/nova/", v.CategoriaCriar.as_view(), name="categoria_despesa_novo"),
    path("categorias/<int:pk>/editar/", v.CategoriaEditar.as_view(), name="categoria_despesa_editar"),
    path("categorias/<int:pk>/excluir/", v.CategoriaExcluir.as_view(), name="categoria_despesa_excluir"),

    # Relatório mensal e fechamento
    path("relatorio/", v.RelatorioMensal.as_view(), name="relatorio_mensal"),
    path("relatorio/csv/", v.RelatorioCsv.as_view(), name="relatorio_csv"),
    path("meses/", v.Meses.as_view(), name="meses"),
    path("meses/fechar/", v.MesAlterar.as_view(acao="fechar"), name="mes_fechar"),
    path("meses/reabrir/", v.MesAlterar.as_view(acao="reabrir"), name="mes_reabrir"),
]
