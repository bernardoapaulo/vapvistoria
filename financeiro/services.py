"""
Cálculos do Financeiro. TODAS as regras de números ficam aqui (views e templates só exibem).
Reaproveita o módulo central do dashboard (`dashboard.services`) para períodos, comparativos,
valor final e faturamento, sem duplicar fórmulas.

DEFINIÇÕES
- Regime de CAIXA (resultado, entradas e saídas, fluxo de caixa):
    receita  = recebimentos NÃO estornados, pela DATA DO RECEBIMENTO;
    despesa  = despesas pagas, pela DATA DO PAGAMENTO.
    Resultado do período = recebimentos - despesas pagas.
    Margem = resultado ÷ recebimentos (vazia se não houve recebimento).
- Regime de COMPETÊNCIA (só estes três usos):
    * A receber: saldo (valor final - recebido) dos atendimentos não cancelados. O vencimento é a
      DATA DO ATENDIMENTO. Atraso = dias entre essa data e hoje. Faixas: a vencer (hoje ou depois),
      1-30, 31-60 e mais de 60 dias.
    * A pagar: despesas sem data de pagamento, pelo VENCIMENTO. Faixas: vencidas, hoje, próximos 7
      dias, 8 a 30 dias e mais adiante.
    * Margem por serviço: receita = faturamento do dashboard (serviços Concluídos no período, pela
      data do atendimento) - despesas DIRETAS do tipo de serviço (pelo vencimento, paga ou não).
      Despesas gerais (sem serviço) aparecem à parte e NÃO são distribuídas.
- Saldo previsto para 30 dias = a receber com vencimento até hoje+30 (inclui o vencido) - a pagar
  com vencimento até hoje+30 (inclui o vencido). Não há saldo inicial de conta: o saldo acumulado
  do fluxo de caixa parte de zero no início do período.
- Faturamento (dashboard de desempenho) ≠ dinheiro recebido: o faturamento conta o serviço
  concluído, mesmo se o cliente ainda não pagou; o financeiro conta o dinheiro que entrou. A tela
  mostra os dois lado a lado (`conciliacao`).
"""
from datetime import date, timedelta

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from atendimentos.models import Atendimento
from dashboard import periodos, services as dash
from dashboard.periodos import Periodo
from servicos.models import TipoServico

from .dinheiro import ZERO
from .models import Despesa, FormaPagamento, Recebimento

Categoria = TipoServico.Categoria


def _soma(qs, campo="valor"):
    return qs.aggregate(t=Sum(campo))["t"] or ZERO


# ---------- Caixa ----------
def total_recebido(periodo):
    return _soma(Recebimento.objects.validos().no_periodo(periodo.inicio, periodo.fim))


def total_pago(periodo):
    return _soma(Despesa.objects.pagas().filter(data_pagamento__gte=periodo.inicio, data_pagamento__lte=periodo.fim))


def margem(resultado, recebido):
    return round(resultado * 100 / recebido, 1) if recebido else None


def resultado_do_periodo(periodo):
    recebido, pago = total_recebido(periodo), total_pago(periodo)
    resultado = recebido - pago
    return {"recebido": recebido, "pago": pago, "resultado": resultado, "margem": margem(resultado, recebido)}


# ---------- A receber (competência) ----------
def a_receber_base(cliente_id=None, de=None, ate=None):
    qs = Atendimento.objects.exclude(status=Atendimento.Status.CANCELADO).annotate(saldo=dash.SALDO).filter(saldo__gt=0)
    if cliente_id:
        qs = qs.filter(cliente_id=cliente_id)
    if de:
        qs = qs.filter(data_atendimento__gte=de)
    if ate:
        qs = qs.filter(data_atendimento__lte=ate)
    return qs


def _intervalos_receber(hoje):
    """chave -> (rótulo, filtro de data_atendimento)."""
    return {
        "a_vencer": ("A vencer", Q(data_atendimento__gte=hoje)),
        "1_30": ("1 a 30 dias", Q(data_atendimento__lt=hoje, data_atendimento__gte=hoje - timedelta(days=30))),
        "31_60": ("31 a 60 dias", Q(data_atendimento__lt=hoje - timedelta(days=30), data_atendimento__gte=hoje - timedelta(days=60))),
        "mais_60": ("Mais de 60 dias", Q(data_atendimento__lt=hoje - timedelta(days=60))),
    }


def filtrar_faixa_receber(qs, chave, hoje=None):
    intervalos = _intervalos_receber(hoje or timezone.localdate())
    return qs.filter(intervalos[chave][1]) if chave in intervalos else qs


def faixas_a_receber(qs, hoje=None):
    hoje = hoje or timezone.localdate()
    intervalos = _intervalos_receber(hoje)
    agregados = {}
    for chave, (_, filtro) in intervalos.items():
        agregados[f"v_{chave}"] = Sum("saldo", filter=filtro)
        agregados[f"n_{chave}"] = Count("pk", filter=filtro)
    r = qs.aggregate(**agregados)
    return [
        {"chave": chave, "rotulo": rotulo, "valor": r[f"v_{chave}"] or ZERO, "quantidade": r[f"n_{chave}"], "atrasada": chave != "a_vencer"}
        for chave, (rotulo, _) in intervalos.items()
    ]


def dias_de_atraso(atendimento, hoje=None):
    return max(((hoje or timezone.localdate()) - atendimento.data_atendimento).days, 0)


# ---------- A pagar (competência) ----------
def a_pagar_base(categoria_id=None):
    qs = Despesa.objects.em_aberto().select_related("categoria", "tipo_servico")
    return qs.filter(categoria_id=categoria_id) if categoria_id else qs


def _intervalos_pagar(hoje):
    return {
        "vencidas": ("Vencidas", Q(vencimento__lt=hoje)),
        "hoje": ("Vencem hoje", Q(vencimento=hoje)),
        "7_dias": ("Próximos 7 dias", Q(vencimento__gt=hoje, vencimento__lte=hoje + timedelta(days=7))),
        "30_dias": ("8 a 30 dias", Q(vencimento__gt=hoje + timedelta(days=7), vencimento__lte=hoje + timedelta(days=30))),
        "depois": ("Mais adiante", Q(vencimento__gt=hoje + timedelta(days=30))),
    }


def filtrar_faixa_pagar(qs, chave, hoje=None):
    intervalos = _intervalos_pagar(hoje or timezone.localdate())
    return qs.filter(intervalos[chave][1]) if chave in intervalos else qs


def faixas_a_pagar(qs, hoje=None):
    hoje = hoje or timezone.localdate()
    intervalos = _intervalos_pagar(hoje)
    agregados = {}
    for chave, (_, filtro) in intervalos.items():
        agregados[f"v_{chave}"] = Sum("valor", filter=filtro)
        agregados[f"n_{chave}"] = Count("pk", filter=filtro)
    r = qs.aggregate(**agregados)
    return [
        {"chave": chave, "rotulo": rotulo, "valor": r[f"v_{chave}"] or ZERO, "quantidade": r[f"n_{chave}"], "atrasada": chave == "vencidas"}
        for chave, (rotulo, _) in intervalos.items()
    ]


# ---------- Previsão ----------
def projecao_30_dias(hoje=None):
    """Tabela simples: entradas e saídas previstas por faixa de data e saldo acumulado."""
    hoje = hoje or timezone.localdate()
    cortes = [  # (rótulo, receber, pagar)
        ("Vencido (já deveria ter entrado/saído)", Q(data_atendimento__lt=hoje), Q(vencimento__lt=hoje)),
        ("Hoje a 7 dias", Q(data_atendimento__gte=hoje, data_atendimento__lte=hoje + timedelta(days=7)),
         Q(vencimento__gte=hoje, vencimento__lte=hoje + timedelta(days=7))),
        ("8 a 15 dias", Q(data_atendimento__gt=hoje + timedelta(days=7), data_atendimento__lte=hoje + timedelta(days=15)),
         Q(vencimento__gt=hoje + timedelta(days=7), vencimento__lte=hoje + timedelta(days=15))),
        ("16 a 30 dias", Q(data_atendimento__gt=hoje + timedelta(days=15), data_atendimento__lte=hoje + timedelta(days=30)),
         Q(vencimento__gt=hoje + timedelta(days=15), vencimento__lte=hoje + timedelta(days=30))),
    ]
    receber, pagar = a_receber_base(), Despesa.objects.em_aberto()
    linhas, acumulado = [], ZERO
    for rotulo, q_receber, q_pagar in cortes:
        entradas, saidas = _soma(receber.filter(q_receber), "saldo"), _soma(pagar.filter(q_pagar))
        acumulado += entradas - saidas
        linhas.append({"rotulo": rotulo, "entradas": entradas, "saidas": saidas, "acumulado": acumulado})
    return {"linhas": linhas, "saldo_previsto": acumulado}


# ---------- Fluxo de caixa ----------
def fluxo_de_caixa(periodo, agrupar="dia"):
    """Entradas, saídas e saldo acumulado (a partir de zero no início do período), por dia ou por mês."""
    recebimentos = Recebimento.objects.validos().no_periodo(periodo.inicio, periodo.fim)
    despesas = Despesa.objects.pagas().filter(data_pagamento__gte=periodo.inicio, data_pagamento__lte=periodo.fim)
    if agrupar == "mes":
        entradas = recebimentos.annotate(g=TruncMonth("data")).values("g").annotate(t=Sum("valor")).order_by()
        saidas = despesas.annotate(g=TruncMonth("data_pagamento")).values("g").annotate(t=Sum("valor")).order_by()
    else:
        entradas = recebimentos.values(g=F("data")).annotate(t=Sum("valor")).order_by()
        saidas = despesas.values(g=F("data_pagamento")).annotate(t=Sum("valor")).order_by()
    e, s = {r["g"]: r["t"] for r in entradas}, {r["g"]: r["t"] for r in saidas}
    linhas, acumulado = [], ZERO
    for chave in sorted(set(e) | set(s)):
        entrada, saida = e.get(chave, ZERO), s.get(chave, ZERO)
        acumulado += entrada - saida
        linhas.append({"data": chave, "entradas": entrada, "saidas": saida, "saldo": entrada - saida, "acumulado": acumulado})
    total_e, total_s = sum((l["entradas"] for l in linhas), ZERO), sum((l["saidas"] for l in linhas), ZERO)
    return {"linhas": linhas, "total_entradas": total_e, "total_saidas": total_s, "saldo": total_e - total_s}


# ---------- Séries e distribuições ----------
def serie_mensal(n=12):
    """Recebimentos x despesas pagas nos últimos n meses (o atual é o último) e o resultado de cada mês."""
    meses = dash.ultimos_meses(n)
    fim = periodos.primeiro_dia_meses_atras(meses[-1], -1) - timedelta(days=1)
    pos = {m: i for i, m in enumerate(meses)}
    entradas, saidas = [ZERO] * n, [ZERO] * n
    for r in (Recebimento.objects.validos().no_periodo(meses[0], fim)
              .annotate(m=TruncMonth("data")).values("m").annotate(t=Sum("valor")).order_by()):
        entradas[pos[r["m"]]] = r["t"]
    for r in (Despesa.objects.pagas().filter(data_pagamento__gte=meses[0], data_pagamento__lte=fim)
              .annotate(m=TruncMonth("data_pagamento")).values("m").annotate(t=Sum("valor")).order_by()):
        saidas[pos[r["m"]]] = r["t"]
    return {"meses": meses, "entradas": entradas, "saidas": saidas, "resultado": [e - s for e, s in zip(entradas, saidas)]}


def despesas_por_categoria(periodo):
    qs = (
        Despesa.objects.pagas().filter(data_pagamento__gte=periodo.inicio, data_pagamento__lte=periodo.fim)
        .values("categoria__nome").annotate(t=Sum("valor")).order_by("-t", "categoria__nome")
    )
    return [(r["categoria__nome"], r["t"]) for r in qs]


def recebimentos_por_forma(periodo):
    valores = {f: ZERO for f in FormaPagamento.values}
    qs = (Recebimento.objects.validos().no_periodo(periodo.inicio, periodo.fim)
          .values("forma").annotate(t=Sum("valor")).order_by())
    for r in qs:
        valores[r["forma"]] = r["t"]
    return valores


def receita_por_categoria(periodo):
    """Dinheiro recebido por categoria de serviço do atendimento (caixa)."""
    valores = {c: ZERO for c in Categoria.values}
    qs = (Recebimento.objects.validos().no_periodo(periodo.inicio, periodo.fim)
          .values("atendimento__tipo_servico__categoria").annotate(t=Sum("valor")).order_by())
    for r in qs:
        valores[r["atendimento__tipo_servico__categoria"]] = r["t"]
    return valores


def margem_por_servico(periodo):
    """Competência: faturamento do tipo de serviço - despesas diretas dele (pelo vencimento). Mais lucrativo primeiro."""
    filtros = dash.Filtros(periodo)
    receita = (
        dash.realizados(dash.no_periodo(dash.atendimentos_base(filtros), periodo))
        .values("tipo_servico_id", "tipo_servico__nome").annotate(t=Sum(dash.VALOR_FINAL)).order_by()
    )
    diretas = (
        Despesa.objects.filter(tipo_servico__isnull=False, vencimento__gte=periodo.inicio, vencimento__lte=periodo.fim)
        .values("tipo_servico_id", "tipo_servico__nome").annotate(t=Sum("valor")).order_by()
    )
    linhas = {}
    for r in receita:
        linhas[r["tipo_servico_id"]] = {"nome": r["tipo_servico__nome"], "receita": r["t"], "despesas": ZERO}
    for r in diretas:
        linha = linhas.setdefault(r["tipo_servico_id"], {"nome": r["tipo_servico__nome"], "receita": ZERO, "despesas": ZERO})
        linha["despesas"] = r["t"]
    resultado = []
    for linha in linhas.values():
        linha["lucro"] = linha["receita"] - linha["despesas"]
        linha["margem"] = margem(linha["lucro"], linha["receita"])
        resultado.append(linha)
    return sorted(resultado, key=lambda l: (-l["lucro"], l["nome"]))


def despesas_gerais(periodo):
    """Despesas sem serviço (aluguel, internet...) pelo vencimento: aparecem à parte, sem rateio."""
    return _soma(Despesa.objects.filter(
        tipo_servico__isnull=True, vencimento__gte=periodo.inicio, vencimento__lte=periodo.fim))


# ---------- Painel ----------
def conciliacao(periodo, recebido):
    """Por que o faturamento do dashboard de desempenho difere do dinheiro recebido."""
    faturamento = dash.faturamento(dash.Filtros(periodo))["faturamento"]
    return {"faturamento": faturamento, "recebido": recebido, "diferenca": faturamento - recebido}


def painel(periodo, hoje=None):
    hoje = hoje or timezone.localdate()
    atual, antes = resultado_do_periodo(periodo), resultado_do_periodo(periodo.anterior)
    receber, pagar = a_receber_base(), a_pagar_base()
    total_receber, total_pagar = _soma(receber, "saldo"), _soma(pagar)
    previsao = projecao_30_dias(hoje)
    return {
        **atual,
        "comparativo": {
            "recebido": dash.variacao(atual["recebido"], antes["recebido"]),
            "pago": dash.variacao(atual["pago"], antes["pago"], menor_e_melhor=True),
            "resultado": dash.variacao(atual["resultado"], antes["resultado"]),
            "margem": dash.variacao_pontos(atual["margem"], antes["margem"]),
        },
        "a_receber": total_receber,
        "a_receber_atrasado": _soma(receber.filter(data_atendimento__lt=hoje), "saldo"),
        "a_pagar": total_pagar,
        "a_pagar_vencido": _soma(pagar.filter(vencimento__lt=hoje)),
        "saldo_previsto": previsao["saldo_previsto"],
        "conciliacao": conciliacao(periodo, atual["recebido"]),
        "serie": serie_mensal(),
        "despesas_categoria": despesas_por_categoria(periodo),
        "formas": recebimentos_por_forma(periodo),
        "receita_categoria": receita_por_categoria(periodo),
        "margem_servico": margem_por_servico(periodo),
        "despesas_gerais": despesas_gerais(periodo),
    }


# ---------- Relatório mensal ----------
def periodo_do_mes(ano, mes):
    inicio = date(ano, mes, 1)
    fim = periodos.primeiro_dia_meses_atras(inicio, -1) - timedelta(days=1)
    return Periodo(periodos.PERSONALIZADO, inicio, fim)


def relatorio_mensal(ano, mes):
    periodo = periodo_do_mes(ano, mes)
    caixa = resultado_do_periodo(periodo)
    receitas = receita_por_categoria(periodo)
    despesas = despesas_por_categoria(periodo)
    pagas = Despesa.objects.pagas().filter(data_pagamento__gte=periodo.inicio, data_pagamento__lte=periodo.fim)
    diretas = _soma(pagas.filter(tipo_servico__isnull=False))
    return {
        "periodo": periodo, **caixa,
        "receitas": [(rotulo, receitas[chave]) for chave, rotulo in Categoria.choices],
        "despesas": despesas,
        "despesas_diretas": diretas,
        "despesas_gerais_pagas": caixa["pago"] - diretas,
        "margem_servico": margem_por_servico(periodo),
    }


# ---------- Página inicial ----------
def resumo_do_mes(hoje=None):
    return resultado_do_periodo(periodos.calcular(periodos.ESTE_MES, hoje=hoje))
