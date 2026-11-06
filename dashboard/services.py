"""
Cálculos do dashboard. TODAS as regras de negócio dos indicadores ficam aqui (views e
templates só exibem), para o módulo financeiro (etapa 5) reutilizar.

DEFINIÇÕES
- Período: sempre pela DATA DO ATENDIMENTO (`data_atendimento`).
- Serviço realizado: atendimento com status Concluído.
- Faturamento: soma de (valor cobrado - desconto) dos atendimentos Concluídos.
  Cancelados nunca entram. Pagamento (pago/pendente) não muda o faturamento.
- Ticket médio: faturamento / serviços realizados.
- Taxa de cancelamento: cancelados / todos os atendimentos com data no período.
- Taxa de conclusão: concluídos / (concluídos + cancelados + em aberto vencidos),
  onde "em aberto vencido" é Solicitado/Agendado/Em andamento com data já passada.
- Taxa de não comparecimento: agendamentos "Não compareceu" / agendamentos do período
  cujo horário de fim já passou (Cancelados e Remarcados não contam: liberaram o horário).
- Cliente novo: o primeiro atendimento não cancelado dele cai no período.
  Cliente recorrente: atendeu no período e já tinha atendimento anterior.
- A receber: (valor final - valor pago) dos atendimentos não cancelados do período.
- Filtro por responsável: o responsável fica no AGENDAMENTO; vale o atendimento que tenha
  algum agendamento daquele responsável.

Tudo é calculado com agregações no banco. As funções "financeiras" (valores em R$) ficam
separadas das "operacionais": a view só chama as financeiras para quem tem permissão, assim
o funcionário nem recebe esses dados.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Min, Prefetch, Q, Sum
from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncMonth
from django.utils import timezone

from agenda.models import Agendamento, limites_do_dia
from atendimentos.models import Atendimento
from financeiro.models import Recebimento
from servicos.models import TipoServico

from . import periodos
from .periodos import Periodo

ZERO = Decimal("0.00")
Status = Atendimento.Status
Categoria = TipoServico.Categoria

VALOR_FINAL = ExpressionWrapper(
    F("valor_cobrado") - F("desconto"), output_field=DecimalField(max_digits=12, decimal_places=2),
)

# Quanto falta receber de cada atendimento (valor final - recebido). `valor_pago` é calculado pelo financeiro.
SALDO = ExpressionWrapper(
    F("valor_cobrado") - F("desconto") - F("valor_pago"), output_field=DecimalField(max_digits=12, decimal_places=2),
)

# Django: ExtractWeekDay devolve 1=domingo ... 7=sábado. Ordem de exibição: segunda a domingo.
DIAS_DA_SEMANA = [("Seg", 2), ("Ter", 3), ("Qua", 4), ("Qui", 5), ("Sex", 6), ("Sáb", 7), ("Dom", 1)]
HORAS_EXIBIDAS = range(6, 22)


@dataclass(frozen=True)
class Filtros:
    periodo: Periodo
    categoria: str = ""
    responsavel_id: int | None = None

    def com_periodo(self, periodo):
        return Filtros(periodo, self.categoria, self.responsavel_id)


# ---------- Bases de consulta ----------
def atendimentos_base(f):
    """Atendimentos (de qualquer data) que respeitam categoria e responsável."""
    qs = Atendimento.objects.all()
    if f.categoria:
        qs = qs.filter(tipo_servico__categoria=f.categoria)
    if f.responsavel_id:
        # subconsulta (e não join), para não repetir linhas e inflar somas
        qs = qs.filter(pk__in=Agendamento.objects.filter(responsavel_id=f.responsavel_id).values("atendimento_id"))
    return qs


def no_periodo(qs, periodo):
    return qs.filter(data_atendimento__gte=periodo.inicio, data_atendimento__lte=periodo.fim)


def realizados(qs):
    return qs.filter(status=Status.CONCLUIDO)


def agendamentos_do_periodo(f, periodo):
    inicio, _ = limites_do_dia(periodo.inicio)
    _, fim = limites_do_dia(periodo.fim)
    qs = Agendamento.objects.filter(inicio__gte=inicio, inicio__lt=fim)
    if f.categoria:
        qs = qs.filter(atendimento__tipo_servico__categoria=f.categoria)
    if f.responsavel_id:
        qs = qs.filter(responsavel_id=f.responsavel_id)
    return qs


# ---------- Comparativos ----------
def _pct(parte, total):
    return round(parte * 100 / total, 1) if total else None


def variacao(atual, anterior, menor_e_melhor=False):
    """Compara dois números. `sentido` ("positivo", "negativo", "neutro") ajuda a colorir."""
    if atual is None or anterior is None:
        return {"texto": "sem base de comparação", "sentido": "neutro"}
    if anterior == 0:
        texto = "sem variação" if atual == 0 else "novo (antes: 0)"
        return {"texto": texto, "sentido": "neutro"}
    pct = (Decimal(atual) - Decimal(anterior)) * 100 / abs(Decimal(anterior))  # módulo: base negativa também funciona
    sentido = "neutro" if round(pct) == 0 else ("positivo" if (pct > 0) != menor_e_melhor else "negativo")
    return {"texto": "0%" if round(pct) == 0 else f"{pct:+.0f}%", "sentido": sentido}


def variacao_pontos(atual, anterior, menor_e_melhor=False):
    """Para taxas: diferença em pontos percentuais."""
    if atual is None or anterior is None:
        return {"texto": "sem base de comparação", "sentido": "neutro"}
    dif = round(atual - anterior, 1)
    sentido = "neutro" if dif == 0 else ("positivo" if (dif > 0) != menor_e_melhor else "negativo")
    return {"texto": f"{dif:+.1f}".replace(".", ",") + " p.p.", "sentido": sentido}


# ---------- Indicadores operacionais (sem valores em R$) ----------
def servicos_por_categoria(qs_realizados):
    contagem = {c: 0 for c in Categoria.values}
    for linha in qs_realizados.values("tipo_servico__categoria").annotate(n=Count("pk")).order_by():
        contagem[linha["tipo_servico__categoria"]] = linha["n"]
    return contagem


def taxas(f, periodo=None):
    p = periodo or f.periodo
    hoje = timezone.localdate()
    a = no_periodo(atendimentos_base(f), p).aggregate(
        total=Count("pk"),
        concluidos=Count("pk", filter=Q(status=Status.CONCLUIDO)),
        cancelados=Count("pk", filter=Q(status=Status.CANCELADO)),
        vencidos=Count("pk", filter=Q(status__in=Atendimento.STATUS_ABERTOS, data_atendimento__lt=hoje)),
    )
    S = Agendamento.Status
    g = (
        agendamentos_do_periodo(f, p).filter(fim__lt=timezone.now())
        .exclude(status__in=[S.CANCELADO, S.REMARCADO])
        .aggregate(total=Count("pk"), faltas=Count("pk", filter=Q(status=S.NAO_COMPARECEU)))
    )
    return {
        "conclusao": _pct(a["concluidos"], a["concluidos"] + a["cancelados"] + a["vencidos"]),
        "cancelamento": _pct(a["cancelados"], a["total"]),
        "nao_comparecimento": _pct(g["faltas"], g["total"]),
    }


def clientes_novos_e_recorrentes(f, periodo=None):
    p = periodo or f.periodo
    ativos = no_periodo(atendimentos_base(f).exclude(status=Status.CANCELADO), p)
    clientes = ativos.values("cliente_id").distinct()
    total = clientes.count()
    # primeiro atendimento (não cancelado) de cada um desses clientes, em qualquer data
    novos = (
        Atendimento.objects.exclude(status=Status.CANCELADO).filter(cliente_id__in=clientes)
        .values("cliente_id").annotate(primeiro=Min("data_atendimento")).filter(primeiro__gte=p.inicio).count()
    )
    return {"novos": novos, "recorrentes": total - novos}


def indicadores_operacionais(f, periodo=None):
    p = periodo or f.periodo
    feitos = realizados(no_periodo(atendimentos_base(f), p))
    por_categoria = servicos_por_categoria(feitos)
    alunos = (
        feitos.filter(tipo_servico__categoria=Categoria.CAPACITACAO).exclude(aluno=None)
        .values("aluno_id").distinct().count()
    )
    t = taxas(f, p)
    c = clientes_novos_e_recorrentes(f, p)
    return {
        "servicos": sum(por_categoria.values()),
        "por_categoria": por_categoria,
        "alunos_atendidos": alunos,
        "taxa_conclusao": t["conclusao"],
        "taxa_cancelamento": t["cancelamento"],
        "taxa_nao_comparecimento": t["nao_comparecimento"],
        "clientes_novos": c["novos"],
        "clientes_recorrentes": c["recorrentes"],
    }


def situacao_atual(f):
    """Foto de agora (não depende do período): o que está em aberto e o que está pendente na agenda."""
    S = Agendamento.Status
    ags = Agendamento.objects.all()
    if f.categoria:
        ags = ags.filter(atendimento__tipo_servico__categoria=f.categoria)
    if f.responsavel_id:
        ags = ags.filter(responsavel_id=f.responsavel_id)
    agora = timezone.now()
    r = ags.filter(status__in=[S.AGENDADO, S.CONFIRMADO]).aggregate(
        pendentes=Count("pk", filter=Q(fim__gte=agora)), atrasados=Count("pk", filter=Q(fim__lt=agora)),
    )
    return {
        "em_aberto": atendimentos_base(f).em_aberto().count(),
        "agendamentos_pendentes": r["pendentes"],
        "agendamentos_atrasados": r["atrasados"],
    }


def distribuicao_status(f):
    contagem = {s: 0 for s in Status.values}
    for linha in no_periodo(atendimentos_base(f), f.periodo).values("status").annotate(n=Count("pk")).order_by():
        contagem[linha["status"]] = linha["n"]
    return contagem


def ultimos_meses(n=12, hoje=None):
    """Primeiro dia de cada um dos últimos n meses (o atual é o último), em ordem."""
    hoje = hoje or timezone.localdate()
    return [periodos.primeiro_dia_meses_atras(hoje, n - 1 - i) for i in range(n)]


def _serie_mensal(f, n, com_valores):
    meses = ultimos_meses(n)
    fim = periodos.primeiro_dia_meses_atras(meses[-1], -1) - timedelta(days=1)  # último dia do mês atual
    qs = (
        realizados(atendimentos_base(f)).filter(data_atendimento__gte=meses[0], data_atendimento__lte=fim)
        .annotate(mes=TruncMonth("data_atendimento")).values("mes", "tipo_servico__categoria").order_by()
    )
    qs = qs.annotate(v=Sum(VALOR_FINAL)) if com_valores else qs.annotate(v=Count("pk"))
    vazio = ZERO if com_valores else 0
    por_categoria = {c: [vazio] * len(meses) for c in Categoria.values}
    posicao = {m: i for i, m in enumerate(meses)}
    for linha in qs:
        por_categoria[linha["tipo_servico__categoria"]][posicao[linha["mes"]]] += linha["v"]
    total = [sum(por_categoria[c][i] for c in por_categoria) for i in range(len(meses))]
    return {"meses": meses, "total": total, "por_categoria": por_categoria}


def movimentacao_mensal(f, n=12):
    """Serviços realizados por mês (e por categoria) nos últimos n meses. Ignora o filtro de período."""
    return _serie_mensal(f, n, com_valores=False)


def ranking_servicos(f, com_valores=False, limite=10):
    qs = (
        realizados(no_periodo(atendimentos_base(f), f.periodo))
        .values("tipo_servico__nome").annotate(n=Count("pk")).order_by()
    )
    if com_valores:
        qs = qs.annotate(faturamento=Sum(VALOR_FINAL))
    qs = qs.order_by("-n", "tipo_servico__nome")[:limite]
    return [
        {"nome": l["tipo_servico__nome"], "n": l["n"], **({"faturamento": l["faturamento"]} if com_valores else {})}
        for l in qs
    ]


def movimento_da_agenda(f):
    """Agendamentos por dia da semana e por hora (fuso America/Sao_Paulo), para organizar a equipe."""
    S = Agendamento.Status
    qs = agendamentos_do_periodo(f, f.periodo).filter(status__in=Agendamento.ATIVOS + [S.CONCLUIDO])
    dias = {l["d"]: l["n"] for l in qs.annotate(d=ExtractWeekDay("inicio")).values("d").annotate(n=Count("pk")).order_by()}
    horas = {l["h"]: l["n"] for l in qs.annotate(h=ExtractHour("inicio")).values("h").annotate(n=Count("pk")).order_by()}
    return {
        "dias": [(rotulo, dias.get(codigo, 0)) for rotulo, codigo in DIAS_DA_SEMANA],
        "horas": [(f"{h}h", horas.get(h, 0)) for h in HORAS_EXIBIDAS],
    }


def servicos_por_responsavel(f):
    """Atendimentos concluídos no período por responsável dos agendamentos."""
    linhas = (
        Agendamento.objects.filter(atendimento__in=realizados(no_periodo(atendimentos_base(f), f.periodo)).values("pk"))
        .exclude(responsavel=None).values("responsavel__username")
        .annotate(n=Count("atendimento_id", distinct=True)).order_by("-n", "responsavel__username")
    )
    return [{"responsavel": l["responsavel__username"], "n": l["n"]} for l in linhas]


def abertos_mais_antigos(f, limite=10):
    hoje = timezone.localdate()
    qs = atendimentos_base(f).em_aberto().select_related("cliente", "tipo_servico").order_by("data_atendimento", "id")[:limite]
    return [{"atendimento": a, "dias": (hoje - a.data_atendimento).days} for a in qs]


def painel_operacional(f):
    """Tudo que o dashboard mostra SEM valores em R$ (vale para qualquer perfil)."""
    atual = indicadores_operacionais(f)
    antes = indicadores_operacionais(f, f.periodo.anterior)
    comparativo = {
        "servicos": variacao(atual["servicos"], antes["servicos"]),
        "por_categoria": {c: variacao(atual["por_categoria"][c], antes["por_categoria"][c]) for c in Categoria.values},
        "taxa_conclusao": variacao_pontos(atual["taxa_conclusao"], antes["taxa_conclusao"]),
        "taxa_cancelamento": variacao_pontos(atual["taxa_cancelamento"], antes["taxa_cancelamento"], menor_e_melhor=True),
        "taxa_nao_comparecimento": variacao_pontos(
            atual["taxa_nao_comparecimento"], antes["taxa_nao_comparecimento"], menor_e_melhor=True),
        "clientes_novos": variacao(atual["clientes_novos"], antes["clientes_novos"]),
        "clientes_recorrentes": variacao(atual["clientes_recorrentes"], antes["clientes_recorrentes"]),
    }
    return {
        "indicadores": atual,
        "comparativo": comparativo,
        "situacao": situacao_atual(f),
        "status": distribuicao_status(f),
        "mensal": movimentacao_mensal(f),
        "ranking": ranking_servicos(f),
        "agenda": movimento_da_agenda(f),
        "por_responsavel": servicos_por_responsavel(f),
        "abertos_antigos": abertos_mais_antigos(f),
    }


# ---------- Indicadores financeiros (valores em R$): só para quem pode ver faturamento ----------
def faturamento(f, periodo=None):
    p = periodo or f.periodo
    r = realizados(no_periodo(atendimentos_base(f), p)).aggregate(total=Sum(VALOR_FINAL), n=Count("pk"))
    total, n = r["total"] or ZERO, r["n"]
    return {"faturamento": total, "ticket_medio": (total / n).quantize(Decimal("0.01")) if n else None}


def a_receber(f, periodo=None):
    p = periodo or f.periodo
    r = no_periodo(atendimentos_base(f).exclude(status=Status.CANCELADO), p).aggregate(
        total=Sum(VALOR_FINAL), pago=Sum("valor_pago"))
    return max((r["total"] or ZERO) - (r["pago"] or ZERO), ZERO)


def faturamento_mensal(f, n=12):
    return _serie_mensal(f, n, com_valores=True)


def faturamento_por_categoria(f):
    valores = {c: ZERO for c in Categoria.values}
    qs = realizados(no_periodo(atendimentos_base(f), f.periodo)).values("tipo_servico__categoria").annotate(v=Sum(VALOR_FINAL)).order_by()
    for linha in qs:
        valores[linha["tipo_servico__categoria"]] = linha["v"]
    return valores


def top_clientes(f, limite=10):
    qs = (
        realizados(no_periodo(atendimentos_base(f), f.periodo)).values("cliente_id", "cliente__nome")
        .annotate(faturamento=Sum(VALOR_FINAL), n=Count("pk")).order_by("-faturamento", "cliente__nome")[:limite]
    )
    return [{"nome": l["cliente__nome"], "n": l["n"], "faturamento": l["faturamento"]} for l in qs]


def situacao_pagamentos(f):
    contagem = {s: 0 for s in Atendimento.SituacaoPagamento.values}
    qs = no_periodo(atendimentos_base(f).exclude(status=Status.CANCELADO), f.periodo)
    for linha in qs.values("situacao_pagamento").annotate(n=Count("pk")).order_by():
        contagem[linha["situacao_pagamento"]] = linha["n"]
    return contagem


def painel_financeiro(f):
    atual = faturamento(f)
    antes = faturamento(f, f.periodo.anterior)
    return {
        "faturamento": atual["faturamento"],
        "ticket_medio": atual["ticket_medio"],
        "comparativo": {
            "faturamento": variacao(atual["faturamento"], antes["faturamento"]),
            "ticket_medio": variacao(atual["ticket_medio"], antes["ticket_medio"]),
        },
        "a_receber": a_receber(f),
        "pagamentos": situacao_pagamentos(f),
        "mensal": faturamento_mensal(f),
        "por_categoria": faturamento_por_categoria(f),
        "ranking": ranking_servicos(f, com_valores=True),
        "top_clientes": top_clientes(f),
    }


def linhas_para_exportar(f):
    """Atendimentos concluídos do período, para o CSV (ordem cronológica)."""
    return (
        realizados(no_periodo(atendimentos_base(f), f.periodo))
        .select_related("cliente", "tipo_servico").order_by("data_atendimento", "id")
        .prefetch_related(Prefetch(
            "recebimentos", queryset=Recebimento.objects.validos().order_by("data", "id"), to_attr="recebimentos_validos"))
    )


# ---------- Resumo da página inicial ----------
def resumo_do_mes(com_valores=False):
    f = Filtros(periodos.calcular(periodos.ESTE_MES))
    resumo = {"servicos": sum(servicos_por_categoria(realizados(no_periodo(atendimentos_base(f), f.periodo))).values())}
    if com_valores:
        resumo["faturamento"] = faturamento(f)["faturamento"]
    return resumo
