"""
Configuração dos gráficos do Financeiro (dados puros em JSON), no mesmo formato do dashboard de
desempenho: o desenho é do static/js/dashboard.js e as cores vêm das variáveis CSS `--cor-<chave>`.
"""
from dashboard.graficos import _numero, _rotulo_mes, _vazio, por_categoria  # noqa: F401  (por_categoria é reaproveitado)

from .models import FormaPagamento


def entradas_e_saidas(serie):
    return {
        "tipo": "bar", "formato": "moeda", "labels": [_rotulo_mes(m) for m in serie["meses"]],
        "series": [
            {"rotulo": "Recebimentos", "cor": "entrada", "dados": [_numero(v) for v in serie["entradas"]]},
            {"rotulo": "Despesas pagas", "cor": "saida", "dados": [_numero(v) for v in serie["saidas"]]},
        ],
        "vazio": _vazio(serie["entradas"]) and _vazio(serie["saidas"]),
    }


def resultado_mensal(serie):
    return {
        "tipo": "bar", "formato": "moeda", "labels": [_rotulo_mes(m) for m in serie["meses"]],
        "series": [{"rotulo": "Resultado", "cor": "grafico-1", "dados": [_numero(v) for v in serie["resultado"]]}],
        "vazio": _vazio(serie["entradas"]) and _vazio(serie["saidas"]),
    }


def despesas_por_categoria(pares):
    """Rosca: a cor de cada fatia é --cor-despesa-1, -2... (o visual muda só no CSS)."""
    dados = [_numero(v) for _, v in pares]
    return {
        "tipo": "doughnut", "formato": "moeda", "labels": [nome for nome, _ in pares],
        "series": [{"rotulo": "Despesas pagas", "cores": [f"despesa-{i % 12 + 1}" for i in range(len(pares))], "dados": dados}],
        "vazio": _vazio(dados),
    }


def formas_de_pagamento(valores):
    chaves = [f for f, _ in FormaPagamento.choices]
    dados = [_numero(valores[c]) for c in chaves]
    return {
        "tipo": "doughnut", "formato": "moeda", "labels": [r for _, r in FormaPagamento.choices],
        "series": [{"rotulo": "Recebimentos", "cores": [f"forma-{c}" for c in chaves], "dados": dados}],
        "vazio": _vazio(dados),
    }


def margem_por_servico(linhas):
    """Barras horizontais com a margem (%) de cada tipo de serviço que teve receita."""
    com_receita = [l for l in linhas if l["margem"] is not None]
    return {
        "tipo": "barh", "formato": "percentual", "labels": [l["nome"] for l in com_receita],
        "series": [{"rotulo": "Margem (%)", "cor": "grafico-2", "dados": [float(l["margem"]) for l in com_receita]}],
        "vazio": not com_receita,
    }
