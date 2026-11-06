"""
Conversão dos pagamentos da etapa 2 (campos do próprio Atendimento) em Recebimentos.

Regras (nada é inventado):
- Pago: um recebimento do valor final, na forma e na data de pagamento já registradas.
- Parcial com valor pago conhecido (maior que zero e menor que o valor final): um recebimento desse valor.
- Faltou forma, data ou valor coerente: NÃO se cria recebimento; o atendimento é marcado em
  `revisar_pagamento` para o Administrador conferir.
Depois disso `valor_pago` e `situacao_pagamento` passam a refletir só o que virou recebimento.

A função recebe o registro de apps da migração (modelos históricos), por isso também roda nos testes.
"""
from decimal import Decimal

ZERO = Decimal("0.00")
OBSERVACAO = "Migrado do pagamento registrado antes do módulo Financeiro."

CATEGORIAS_PADRAO = [
    "Aluguel", "Água/Luz/Internet", "Salários e encargos", "Impostos e taxas", "Material de limpeza",
    "Peças e reparos", "Combustível", "Equipamentos", "Marketing", "Manutenção", "Instrutores/cursos", "Outros",
]


def criar_categorias(apps, schema_editor=None):
    Categoria = apps.get_model("financeiro", "CategoriaDespesa")
    for nome in CATEGORIAS_PADRAO:
        Categoria.objects.get_or_create(nome=nome)


def converter_pagamentos(apps, schema_editor=None):
    """Retorna (recebimentos criados, atendimentos marcados para revisão)."""
    Atendimento = apps.get_model("atendimentos", "Atendimento")
    Recebimento = apps.get_model("financeiro", "Recebimento")
    Auditoria = apps.get_model("financeiro", "RegistroAuditoria")

    criados, revisar = 0, 0
    for a in Atendimento.objects.exclude(situacao_pagamento="pendente").iterator():
        final = a.valor_cobrado - a.desconto
        pago = final if a.situacao_pagamento == "pago" else a.valor_pago
        completo = bool(a.forma_pagamento and a.data_pagamento and ZERO < pago <= final)
        if a.situacao_pagamento == "pago" and final <= 0:
            continue  # atendimento sem valor a receber: não há o que converter nem revisar
        if completo:
            r = Recebimento.objects.create(
                atendimento=a, valor=pago, data=a.data_pagamento, forma=a.forma_pagamento, observacao=OBSERVACAO)
            Auditoria.objects.create(
                entidade="recebimento", objeto_id=r.pk, acao="criado", descricao=OBSERVACAO)
            a.valor_pago = pago
            criados += 1
        else:
            a.valor_pago, a.situacao_pagamento, a.revisar_pagamento = ZERO, "pendente", True
            revisar += 1
        if completo:
            a.situacao_pagamento = "pago" if pago >= final else "parcial"
        Atendimento.objects.filter(pk=a.pk).update(
            valor_pago=a.valor_pago, situacao_pagamento=a.situacao_pagamento, revisar_pagamento=a.revisar_pagamento)
    return criados, revisar
