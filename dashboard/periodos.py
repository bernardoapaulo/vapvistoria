"""
Períodos do dashboard e o período anterior usado no comparativo.

Todos os períodos terminam HOJE (o futuro ainda não aconteceu), exceto "Mês passado"
e "Personalizado". Datas são `date` no fuso do projeto (America/Sao_Paulo).
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

ESTE_MES = "este_mes"
MES_PASSADO = "mes_passado"
ULTIMOS_3_MESES = "ultimos_3_meses"
ULTIMOS_6_MESES = "ultimos_6_meses"
ESTE_ANO = "este_ano"
PERSONALIZADO = "personalizado"

OPCOES = [
    (ESTE_MES, "Este mês"),
    (MES_PASSADO, "Mês passado"),
    (ULTIMOS_3_MESES, "Últimos 3 meses"),
    (ULTIMOS_6_MESES, "Últimos 6 meses"),
    (ESTE_ANO, "Este ano"),
    (PERSONALIZADO, "Personalizado"),
]

_COMPARATIVO = {
    ESTE_MES: "vs. mês passado",
    MES_PASSADO: "vs. mês retrasado",
    ESTE_ANO: "vs. ano passado",
}


@dataclass(frozen=True)
class Periodo:
    chave: str
    inicio: date  # inclusive
    fim: date     # inclusive

    @property
    def dias(self):
        return (self.fim - self.inicio).days + 1

    @property
    def rotulo(self):
        return dict(OPCOES).get(self.chave, "Período")

    @property
    def rotulo_comparativo(self):
        return _COMPARATIVO.get(self.chave, "vs. período anterior")

    @property
    def anterior(self):
        return periodo_anterior(self)


def primeiro_dia_meses_atras(dia, meses):
    """Primeiro dia do mês que fica `meses` meses antes do mês de `dia`."""
    indice = dia.year * 12 + (dia.month - 1) - meses
    return date(indice // 12, indice % 12 + 1, 1)


def _ultimo_dia_do_mes(dia):
    return date(dia.year, dia.month, calendar.monthrange(dia.year, dia.month)[1])


def calcular(chave, de=None, ate=None, hoje=None):
    """Monta o Período escolhido. Chave desconhecida ou datas inválidas viram "Este mês"."""
    hoje = hoje or timezone.localdate()
    if chave == MES_PASSADO:
        inicio = primeiro_dia_meses_atras(hoje, 1)
        return Periodo(chave, inicio, _ultimo_dia_do_mes(inicio))
    if chave == ULTIMOS_3_MESES:  # 3 meses de calendário: o atual e os 2 anteriores
        return Periodo(chave, primeiro_dia_meses_atras(hoje, 2), hoje)
    if chave == ULTIMOS_6_MESES:
        return Periodo(chave, primeiro_dia_meses_atras(hoje, 5), hoje)
    if chave == ESTE_ANO:
        return Periodo(chave, date(hoje.year, 1, 1), hoje)
    if chave == PERSONALIZADO and de and ate:
        de, ate = min(de, ate), max(de, ate)
        return Periodo(chave, de, ate)
    return Periodo(ESTE_MES, hoje.replace(day=1), hoje)


def periodo_anterior(p):
    """
    Período de mesma duração logo antes. Para "Este mês" e "Este ano", compara o mesmo
    trecho do mês/ano anterior (dia 1 até o mesmo dia), a comparação justa para um período em andamento.
    """
    if p.chave == MES_PASSADO:  # mês fechado contra o mês fechado anterior
        inicio = primeiro_dia_meses_atras(p.inicio, 1)
        return Periodo(p.chave, inicio, _ultimo_dia_do_mes(inicio))
    if p.chave == ESTE_MES:
        inicio = primeiro_dia_meses_atras(p.inicio, 1)
        return Periodo(p.chave, inicio, min(inicio + timedelta(days=p.dias - 1), _ultimo_dia_do_mes(inicio)))
    if p.chave == ESTE_ANO:
        inicio = date(p.inicio.year - 1, 1, 1)
        return Periodo(p.chave, inicio, min(inicio + timedelta(days=p.dias - 1), date(inicio.year, 12, 31)))
    fim = p.inicio - timedelta(days=1)
    return Periodo(p.chave, fim - timedelta(days=p.dias - 1), fim)
