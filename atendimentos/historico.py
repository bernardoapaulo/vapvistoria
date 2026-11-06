"""
Único ponto do sistema que muda status/pagamento de um atendimento e grava o
histórico. Formulários e botões rápidos chamam estas funções, assim o histórico
nunca fica de fora e sempre sabe QUEM fez a mudança.
"""
from django.db import transaction
from financeiro.dinheiro import reais

from .models import Atendimento, HistoricoAtendimento

Tipo = HistoricoAtendimento.Tipo
Sit = Atendimento.SituacaoPagamento


real = reais  # moeda brasileira: R$ 1.234,50


def _texto_pagamento(a):
    texto = a.get_situacao_pagamento_display()
    if a.situacao_pagamento == Sit.PARCIAL:
        texto += f" ({real(a.valor_pago)})"
    return texto


def estado(a):
    """Foto do que interessa ao histórico, para comparar antes/depois."""
    return {
        "status": a.status,
        "status_texto": a.get_status_display(),
        "pagamento": _texto_pagamento(a),
        "valor": f"{real(a.valor_cobrado)} (desconto {real(a.desconto)})",
    }


def _gravar(a, tipo, anterior, novo, usuario):
    HistoricoAtendimento.objects.create(
        atendimento=a, tipo=tipo, valor_anterior=anterior, valor_novo=novo, usuario=usuario,
    )


def registrar_criacao(a, usuario):
    _gravar(a, Tipo.CRIACAO, "", f"Atendimento criado ({a.get_status_display()})", usuario)


def registrar_agenda(a, texto, usuario):
    """Anota na linha do tempo do atendimento algo que aconteceu na agenda."""
    _gravar(a, Tipo.AGENDA, "", texto, usuario)


def registrar_mudancas(a, antes, usuario):
    """Compara o estado anterior com o atual e grava uma linha por mudança."""
    depois = estado(a)
    if antes["status"] != depois["status"]:
        reabertura = antes["status"] in Atendimento.STATUS_FECHADOS and a.aberto
        _gravar(a, Tipo.REABERTURA if reabertura else Tipo.STATUS,
                antes["status_texto"], depois["status_texto"], usuario)
    if antes["pagamento"] != depois["pagamento"]:
        _gravar(a, Tipo.PAGAMENTO, antes["pagamento"], depois["pagamento"], usuario)
    if antes["valor"] != depois["valor"]:
        _gravar(a, Tipo.VALOR, antes["valor"], depois["valor"], usuario)


@transaction.atomic
def alterar_status(a, novo_status, usuario):
    antes = estado(a)
    a.status = novo_status
    a.save(update_fields=["status", "atualizado_em"])
    registrar_mudancas(a, antes, usuario)


def registrar_pagamento(a, texto_antes, detalhe, usuario):
    """Linha do histórico para um recebimento, estorno ou ajuste: "Pendente -> Parcial (R$ 100,00) · detalhe"."""
    _gravar(a, Tipo.PAGAMENTO, texto_antes, f"{_texto_pagamento(a)} · {detalhe}", usuario)
