"""
Monta a configuração dos gráficos (dados puros, em JSON) a partir dos números de services.py.
O desenho é feito pelo static/js/dashboard.js (Chart.js). As cores NÃO ficam aqui: cada série
traz só uma chave (ex.: "categoria-limpeza"), e o JavaScript lê a variável CSS `--cor-<chave>`.
"""
from datetime import date

from atendimentos.models import Atendimento
from servicos.models import TipoServico

Categoria = TipoServico.Categoria

MESES_ABREVIADOS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _numero(v):
    return float(v)  # Decimal não vira JSON; o gráfico trabalha com números comuns


def _rotulo_mes(d: date):
    return f"{MESES_ABREVIADOS[d.month - 1]}/{d.year % 100:02d}"


def _vazio(valores):
    return not any(valores)


def _serie_categorias(por_categoria):
    return [
        {"rotulo": rotulo, "cor": f"categoria-{chave}", "dados": [_numero(v) for v in por_categoria[chave]]}
        for chave, rotulo in Categoria.choices
    ]


def mensal(dados, rotulo_total, formato="numero"):
    """Barras por mês; o usuário pode empilhar por categoria."""
    return {
        "tipo": "bar", "formato": formato, "empilhavel": True,
        "labels": [_rotulo_mes(m) for m in dados["meses"]],
        "series": [{"rotulo": rotulo_total, "cor": "grafico-1", "dados": [_numero(v) for v in dados["total"]]}],
        "series_empilhadas": _serie_categorias(dados["por_categoria"]),
        "vazio": _vazio(dados["total"]),
    }


def por_categoria(valores, formato="numero"):
    """Rosca com uma fatia por categoria (valores: dict categoria -> número)."""
    chaves = [c for c, _ in Categoria.choices]
    dados = [_numero(valores[c]) for c in chaves]
    return {
        "tipo": "doughnut", "formato": formato, "labels": [r for _, r in Categoria.choices],
        "series": [{"rotulo": "Categorias", "cores": [f"categoria-{c}" for c in chaves], "dados": dados}],
        "vazio": _vazio(dados),
    }


def ranking(linhas):
    return {
        "tipo": "barh", "formato": "numero", "labels": [l["nome"] for l in linhas],
        "series": [{"rotulo": "Serviços realizados", "cor": "grafico-1", "dados": [l["n"] for l in linhas]}],
        "vazio": not linhas,
    }


def status(contagem):
    chaves = [s for s, _ in Atendimento.Status.choices]
    dados = [contagem[s] for s in chaves]
    return {
        "tipo": "doughnut", "formato": "numero", "labels": [r for _, r in Atendimento.Status.choices],
        "series": [{"rotulo": "Atendimentos", "cores": [f"status-{s}" for s in chaves], "dados": dados}],
        "vazio": _vazio(dados),
    }


def pagamentos(contagem):
    chaves = [s for s, _ in Atendimento.SituacaoPagamento.choices]
    dados = [contagem[s] for s in chaves]
    return {
        "tipo": "doughnut", "formato": "numero",
        "labels": [r for _, r in Atendimento.SituacaoPagamento.choices],
        "series": [{"rotulo": "Atendimentos", "cores": [f"pagto-{s}" for s in chaves], "dados": dados}],
        "vazio": _vazio(dados),
    }


def barras_simples(pares, rotulo):
    """Lista de (rótulo, quantidade): dias da semana e horários."""
    dados = [n for _, n in pares]
    return {
        "tipo": "bar", "formato": "numero", "labels": [r for r, _ in pares],
        "series": [{"rotulo": rotulo, "cor": "grafico-2", "dados": dados}],
        "vazio": _vazio(dados),
    }
