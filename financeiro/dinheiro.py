"""
Dinheiro: arredondamento em centavos e formatação em reais. Sem dependência de modelos,
para poder ser usado em qualquer app. Valores monetários são sempre Decimal (nunca float).
"""
from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")


def centavos(valor):
    """Arredonda para 2 casas, sempre "meio para cima" (0,005 -> 0,01), em qualquer lugar do sistema."""
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def reais(valor):
    """R$ 1.234,56 (negativo: -R$ 1.234,56). None vira um traço."""
    if valor is None:
        return "—"
    valor = centavos(valor)
    texto = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {texto}" if valor < 0 else f"R$ {texto}"


def percentual(valor):
    """12,5% (None vira um traço)."""
    if valor is None:
        return "—"
    return f"{valor:.1f}".replace(".", ",") + "%"
