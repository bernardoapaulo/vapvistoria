"""
Regras de negócio do Financeiro. É o ÚNICO lugar que cria, altera ou estorna lançamentos:
formulários e botões chamam estas funções, assim as validações, a trava de mês fechado, o
histórico do atendimento e a auditoria nunca ficam de fora. Cada operação que mexe em mais de
uma tabela roda dentro de `transaction.atomic`.

Erros de regra de negócio saem como `ValidationError` (mensagem em português, pronta para a tela).
"""
import calendar
from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from atendimentos import historico
from atendimentos.models import Atendimento
from dashboard.periodos import primeiro_dia_meses_atras

from .dinheiro import ZERO, centavos, reais
from .models import Despesa, FechamentoMes, Recebimento, RegistroAuditoria

Sit = Atendimento.SituacaoPagamento
Entidade = RegistroAuditoria.Entidade


# ---------- Auditoria ----------
def auditar(entidade, objeto_id, acao, descricao, usuario):
    RegistroAuditoria.objects.create(
        entidade=entidade, objeto_id=objeto_id, acao=acao, descricao=descricao, usuario=usuario)


def descrever_mudancas(antes, depois):
    """Compara dois dicts {rótulo: valor} e devolve "rótulo: antes -> depois; ..." (vazio se nada mudou)."""
    partes = []
    for rotulo, valor_antes in antes.items():
        if valor_antes != depois[rotulo]:
            partes.append(f"{rotulo}: {valor_antes or '—'} → {depois[rotulo] or '—'}")
    return "; ".join(partes)


# ---------- Fechamento de mês ----------
def mes_fechado(data):
    return FechamentoMes.objects.filter(mes=data.replace(day=1), fechado=True).exists()


def meses_fechados():
    return set(FechamentoMes.objects.filter(fechado=True).values_list("mes", flat=True))


def exigir_mes_aberto(*datas, acao="alterar lançamentos"):
    """Barra a operação se alguma das datas cai num mês fechado."""
    for mes in sorted({d.replace(day=1) for d in datas if d}):
        if mes_fechado(mes):
            raise ValidationError(
                f"O mês {mes:%m/%Y} está fechado: não é possível {acao} com data nele. "
                "Um administrador pode reabrir o mês em Financeiro > Meses.")


@transaction.atomic
def fechar_mes(mes, usuario):
    mes = mes.replace(day=1)
    if mes >= timezone.localdate().replace(day=1):
        raise ValidationError("Só é possível fechar meses que já terminaram.")
    fechamento, _ = FechamentoMes.objects.get_or_create(mes=mes)
    if fechamento.fechado and fechamento.fechado_em:
        raise ValidationError(f"O mês {mes:%m/%Y} já está fechado.")
    fechamento.fechado, fechamento.fechado_por, fechamento.fechado_em = True, usuario, timezone.now()
    fechamento.save()
    auditar(Entidade.MES, mes.year * 100 + mes.month, "fechado", f"Mês {mes:%m/%Y} fechado.", usuario)
    return fechamento


@transaction.atomic
def reabrir_mes(mes, usuario):
    mes = mes.replace(day=1)
    fechamento = FechamentoMes.objects.filter(mes=mes, fechado=True).first()
    if not fechamento:
        raise ValidationError(f"O mês {mes:%m/%Y} não está fechado.")
    fechamento.fechado, fechamento.reaberto_por, fechamento.reaberto_em = False, usuario, timezone.now()
    fechamento.save()
    auditar(Entidade.MES, mes.year * 100 + mes.month, "reaberto", f"Mês {mes:%m/%Y} reaberto.", usuario)
    return fechamento


# ---------- Recebimentos ----------
def recalcular_pagamento(atendimento):
    """
    Situação do pagamento CALCULADA: soma dos recebimentos não estornados contra o valor devido
    (valor cobrado - desconto). Único lugar que grava `valor_pago` e `situacao_pagamento`.
    """
    recebido = atendimento.recebimentos.validos().aggregate(t=Sum("valor"))["t"] or ZERO
    devido = atendimento.valor_final
    if devido > 0 and recebido >= devido:
        situacao = Sit.PAGO
    elif recebido > 0:
        situacao = Sit.PARCIAL
    else:
        situacao = Sit.PENDENTE
    atendimento.valor_pago, atendimento.situacao_pagamento = recebido, situacao
    atendimento.save(update_fields=["valor_pago", "situacao_pagamento", "atualizado_em"])


def _validar_valor_e_data(valor, data):
    if valor is None or valor <= 0:
        raise ValidationError("O valor deve ser maior que zero.")
    if data is None:
        raise ValidationError("Informe a data do recebimento.")
    if data > timezone.localdate():
        raise ValidationError("A data do recebimento não pode ser no futuro.")


@transaction.atomic
def registrar_recebimento(atendimento, valor, data, forma, observacao, usuario):
    """Registra dinheiro recebido; o total recebido nunca ultrapassa o valor devido."""
    a = Atendimento.objects.select_for_update().get(pk=atendimento.pk)
    valor = centavos(valor)
    if a.status == Atendimento.Status.CANCELADO:
        raise ValidationError("Atendimento cancelado não recebe pagamentos.")
    _validar_valor_e_data(valor, data)
    exigir_mes_aberto(data, acao="registrar recebimentos")
    recebido = a.recebimentos.validos().aggregate(t=Sum("valor"))["t"] or ZERO
    saldo = a.valor_final - recebido
    if valor > saldo:
        raise ValidationError(
            f"O valor informado ({reais(valor)}) é maior que o saldo a receber deste atendimento ({reais(saldo)}).")

    antes = historico.estado(a)["pagamento"]
    r = Recebimento.objects.create(
        atendimento=a, valor=valor, data=data, forma=forma, observacao=(observacao or "").strip(),
        criado_por=usuario, alterado_por=usuario)
    recalcular_pagamento(a)
    historico.registrar_pagamento(
        a, antes, f"recebimento de {reais(valor)} via {r.get_forma_display()} em {data:%d/%m/%Y}", usuario)
    auditar(Entidade.RECEBIMENTO, r.pk, "criado",
            f"Recebimento de {reais(valor)} ({r.get_forma_display()}, {data:%d/%m/%Y}) no atendimento #{a.pk}.", usuario)
    atendimento.valor_pago, atendimento.situacao_pagamento = a.valor_pago, a.situacao_pagamento
    return r


@transaction.atomic
def estornar_recebimento(recebimento, motivo, usuario):
    """O recebimento fica registrado como estornado (nunca é apagado) e deixa de contar no caixa."""
    r = Recebimento.objects.select_for_update().select_related("atendimento").get(pk=recebimento.pk)
    motivo = (motivo or "").strip()
    if r.estornado:
        raise ValidationError("Este recebimento já foi estornado.")
    if len(motivo) < 3:
        raise ValidationError("Informe o motivo do estorno.")
    exigir_mes_aberto(r.data, acao="estornar recebimentos")

    a = r.atendimento
    antes = historico.estado(a)["pagamento"]
    r.estornado_em, r.estornado_por, r.motivo_estorno, r.alterado_por = timezone.now(), usuario, motivo[:300], usuario
    r.save()
    recalcular_pagamento(a)
    historico.registrar_pagamento(a, antes, f"estorno de {reais(r.valor)} ({r.get_forma_display()}): {motivo}", usuario)
    auditar(Entidade.RECEBIMENTO, r.pk, "estornado", f"Estorno de {reais(r.valor)}. Motivo: {motivo}", usuario)
    recebimento.estornado_em, recebimento.motivo_estorno = r.estornado_em, r.motivo_estorno
    return r


@transaction.atomic
def editar_recebimento(recebimento, valor, data, forma, observacao, usuario):
    """Altera um recebimento (Administrador). Mudanças ficam na auditoria e, se for valor, no histórico do atendimento."""
    r = Recebimento.objects.select_for_update().select_related("atendimento").get(pk=recebimento.pk)
    if r.estornado:
        raise ValidationError("Recebimento estornado não pode ser editado.")
    valor = centavos(valor)
    _validar_valor_e_data(valor, data)
    exigir_mes_aberto(r.data, data, acao="editar recebimentos")

    a = Atendimento.objects.select_for_update().get(pk=r.atendimento_id)
    outros = a.recebimentos.validos().exclude(pk=r.pk).aggregate(t=Sum("valor"))["t"] or ZERO
    if outros + valor > a.valor_final:
        raise ValidationError(
            f"O valor informado ({reais(valor)}) ultrapassa o saldo deste atendimento "
            f"({reais(a.valor_final - outros)}).")

    antes = {"valor": reais(r.valor), "data": f"{r.data:%d/%m/%Y}", "forma": r.get_forma_display(), "observação": r.observacao}
    valor_antes_pagamento = historico.estado(a)["pagamento"]
    r.valor, r.data, r.forma, r.observacao, r.alterado_por = valor, data, forma, (observacao or "").strip(), usuario
    r.save()
    depois = {"valor": reais(r.valor), "data": f"{r.data:%d/%m/%Y}", "forma": r.get_forma_display(), "observação": r.observacao}
    mudancas = descrever_mudancas(antes, depois)
    if mudancas:
        auditar(Entidade.RECEBIMENTO, r.pk, "alterado", mudancas, usuario)
        recalcular_pagamento(a)
        if antes["valor"] != depois["valor"]:
            historico.registrar_pagamento(
                a, valor_antes_pagamento, f"recebimento ajustado de {antes['valor']} para {depois['valor']}", usuario)
    recebimento.valor, recebimento.data, recebimento.forma, recebimento.observacao = r.valor, r.data, r.forma, r.observacao
    return r


# ---------- Despesas ----------
def _foto_despesa(d):
    return {
        "descrição": d.descricao, "categoria": str(d.categoria), "valor": reais(d.valor),
        "vencimento": f"{d.vencimento:%d/%m/%Y}",
        "pagamento": f"{d.data_pagamento:%d/%m/%Y}" if d.data_pagamento else "",
        "forma": d.get_forma_pagamento_display() if d.forma_pagamento else "",
        "serviço": str(d.tipo_servico) if d.tipo_servico_id else "",
    }


def foto_despesa(d):
    return _foto_despesa(d)


def validar_despesa(antes_data, d):
    """`antes_data`: data de lançamento antes da edição (None se nova). Barra mês fechado e datas futuras de pagamento."""
    if d.data_pagamento and d.data_pagamento > timezone.localdate():
        raise ValidationError("A data do pagamento não pode ser no futuro. Deixe em branco se ainda não foi paga.")
    if d.data_pagamento and not d.forma_pagamento:
        raise ValidationError("Informe a forma de pagamento da despesa paga.")
    exigir_mes_aberto(antes_data, d.data_lancamento, acao="criar ou editar despesas")


@transaction.atomic
def salvar_despesa(d, antes_foto, usuario):
    """Grava (criando ou editando) e audita. `antes_foto` vem de `foto_despesa` antes da edição (None se nova)."""
    criando = d.pk is None
    if criando:
        d.criado_por = usuario
    d.alterado_por = usuario
    d.save()
    if criando:
        auditar(Entidade.DESPESA, d.pk, "criado", f"Despesa criada: {d.descricao} ({reais(d.valor)}).", usuario)
    else:
        mudancas = descrever_mudancas(antes_foto, _foto_despesa(d))
        if mudancas:
            auditar(Entidade.DESPESA, d.pk, "alterado", mudancas, usuario)
    return d


@transaction.atomic
def pagar_despesa(d, data, forma, usuario):
    d = Despesa.objects.select_for_update().get(pk=d.pk)
    if d.paga:
        raise ValidationError("Esta despesa já está paga.")
    if data is None or data > timezone.localdate():
        raise ValidationError("Informe uma data de pagamento que não seja futura.")
    if not forma:
        raise ValidationError("Informe a forma de pagamento.")
    exigir_mes_aberto(data, acao="registrar pagamentos")
    d.data_pagamento, d.forma_pagamento, d.alterado_por = data, forma, usuario
    d.save()
    auditar(Entidade.DESPESA, d.pk, "pago", f"Pagamento de {reais(d.valor)} em {data:%d/%m/%Y} ({d.get_forma_pagamento_display()}).", usuario)
    return d


@transaction.atomic
def excluir_despesa(d, usuario):
    """Só Administrador (a view confere). Fica um resumo na auditoria; o comprovante sai do disco."""
    exigir_mes_aberto(d.data_lancamento, acao="excluir despesas")
    resumo = "; ".join(f"{k}: {v}" for k, v in _foto_despesa(d).items() if v)
    auditar(Entidade.DESPESA, d.pk, "excluido", f"Despesa excluída ({resumo}).", usuario)
    arquivo = d.comprovante
    d.delete()
    if arquivo:
        transaction.on_commit(lambda: arquivo.storage.delete(arquivo.name))


# ---------- Despesas recorrentes ----------
def _dia_no_mes(dia, mes):
    """O mesmo dia no mês dado; dia 31 num mês de 30 dias vira o último dia do mês."""
    return date(mes.year, mes.month, min(dia, calendar.monthrange(mes.year, mes.month)[1]))


def gerar_recorrentes(hoje=None, meses_a_frente=2):
    """
    Cria as despesas dos próximos meses a partir das marcadas como "repetir todo mês".
    Pode rodar quantas vezes quiser: um mês que já tem a despesa (gerada ou editada) é pulado, e
    uma restrição única no banco (origem + vencimento) é a garantia final contra duplicar.
    Chamada ao abrir o Financeiro e pelo comando `gerar_despesas_recorrentes`. Retorna quantas criou.
    """
    hoje = hoje or timezone.localdate()
    limite = primeiro_dia_meses_atras(hoje, -meses_a_frente)
    fechados = meses_fechados()
    criadas = 0
    for modelo in Despesa.objects.filter(recorrente=True, origem__isnull=True).select_related("categoria"):
        existentes = {(v.year, v.month) for v in modelo.recorrencias.values_list("vencimento", flat=True)}
        existentes.add((modelo.vencimento.year, modelo.vencimento.month))
        mes = primeiro_dia_meses_atras(modelo.vencimento.replace(day=1), -1)
        while mes <= limite:
            if (mes.year, mes.month) not in existentes and mes not in fechados:
                vencimento = _dia_no_mes(modelo.vencimento.day, mes)
                try:
                    with transaction.atomic():
                        nova = Despesa.objects.create(
                            descricao=modelo.descricao, categoria=modelo.categoria, valor=modelo.valor,
                            vencimento=vencimento, fornecedor=modelo.fornecedor, observacao=modelo.observacao,
                            tipo_servico=modelo.tipo_servico, origem=modelo,
                            criado_por=modelo.criado_por, alterado_por=modelo.criado_por)
                        auditar(Entidade.DESPESA, nova.pk, "criado",
                                f"Gerada automaticamente (recorrência da despesa #{modelo.pk}).", None)
                    criadas += 1
                except IntegrityError:
                    pass  # outra requisição gerou no mesmo instante
            mes = primeiro_dia_meses_atras(mes, -1)
    return criadas
