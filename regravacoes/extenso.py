"""Valor em reais por extenso, em português do Brasil (usado no Recibo de Pagamento)."""
from decimal import ROUND_HALF_UP, Decimal

UNIDADES = ["", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
            "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
            "oitocentos", "novecentos"]
ESCALAS = [("", ""), ("mil", "mil"), ("milhão", "milhões"), ("bilhão", "bilhões"), ("trilhão", "trilhões")]


def _ate_999(n):
    """0 < n < 1000 por extenso."""
    if n == 100:
        return "cem"
    centena, resto = divmod(n, 100)
    partes = []
    if centena:
        partes.append(CENTENAS[centena])
    if resto:
        if resto < 20:
            partes.append(UNIDADES[resto])
        else:
            dezena, unidade = divmod(resto, 10)
            partes.append(DEZENAS[dezena] + (f" e {UNIDADES[unidade]}" if unidade else ""))
    return " e ".join(partes)


def inteiro_por_extenso(n):
    """Inteiro não negativo por extenso (sem a palavra "reais")."""
    if n == 0:
        return "zero"
    grupos = []
    escala = 0
    while n:
        n, grupo = divmod(n, 1000)
        if grupo:
            if escala == 1 and grupo == 1:
                texto = "mil"                          # "mil", não "um mil"
            else:
                singular, plural = ESCALAS[escala]
                texto = _ate_999(grupo) + (f" {singular if grupo == 1 else plural}" if escala else "")
            grupos.append((grupo, texto))
        escala += 1
    grupos.reverse()
    resultado = grupos[0][1]
    for i, (grupo, texto) in enumerate(grupos[1:], start=1):
        ultimo = i == len(grupos) - 1
        junta_com_e = ultimo and (grupo < 100 or grupo % 100 == 0)
        resultado += (" e " if junta_com_e else ", ") + texto
    return resultado


def valor_por_extenso(valor):
    """Ex.: Decimal("1234.56") -> "mil, duzentos e trinta e quatro reais e cinquenta e seis centavos"."""
    valor = Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if valor < 0:
        raise ValueError("Valor negativo não tem extenso de recibo.")
    reais, centavos = divmod(int((valor * 100).to_integral_value()), 100)
    partes = []
    if reais or not centavos:
        texto = inteiro_por_extenso(reais)
        # "um milhão DE reais", "dois bilhões DE reais": o "de" entra quando só há milhões/bilhões/trilhões redondos
        de = " de" if reais >= 1_000_000 and reais % 1_000_000 == 0 else ""
        partes.append(f"{texto}{de} {'real' if reais in (0, 1) else 'reais'}")
    if centavos:
        partes.append(f"{inteiro_por_extenso(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
    return " e ".join(partes)
