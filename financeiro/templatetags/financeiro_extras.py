from django import template

from financeiro import dinheiro

register = template.Library()


@register.filter
def moeda(valor):
    """{{ valor|moeda }} -> R$ 1.234,56"""
    return dinheiro.reais(valor)


@register.filter
def porcento(valor):
    """{{ taxa|porcento }} -> 12,5%"""
    return dinheiro.percentual(valor)
