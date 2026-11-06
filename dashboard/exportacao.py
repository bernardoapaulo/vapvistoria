"""CSV que abre direto no Excel em português: separador ";", UTF-8 com BOM e vírgula decimal."""
import csv

from django.http import HttpResponse


def texto_seguro(valor):
    """Evita que o Excel execute como fórmula um texto que comece com = + - @."""
    valor = str(valor)
    return "'" + valor if valor[:1] in ("=", "+", "-", "@", "\t", "\r") else valor


def numero_br(valor):
    return f"{valor:.2f}".replace(".", ",")


def resposta_csv(nome_arquivo):
    """Devolve (resposta, escritor). O BOM faz o Excel reconhecer os acentos."""
    resposta = HttpResponse(content_type="text/csv; charset=utf-8")
    resposta["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    resposta.write("﻿")
    return resposta, csv.writer(resposta, delimiter=";")
