"""
Gera atendimentos FICTÍCIOS espalhados pelos últimos 12 meses (com histórico), com
sazonalidade (meses mais fortes e mais fracos), crescimento leve e clientes recorrentes,
para testar listagens, o dashboard e o financeiro (recebimentos à vista, parcelados, parciais e pendentes).
Usado pelo comando `popular_dados`. Nunca usa dados reais.
"""
import random
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from cadastros.models import Aluno, Cliente, Veiculo
from servicos.models import TipoServico

from financeiro.models import FormaPagamento, Recebimento, RegistroAuditoria

from . import historico
from .models import Atendimento, HistoricoAtendimento

Status = Atendimento.Status
Sit = Atendimento.SituacaoPagamento
Tipo = HistoricoAtendimento.Tipo

OBSERVACOES = ["", "", "", "Cliente pediu urgência.", "Retornar contato por WhatsApp.", "Documentação conferida."]


# Peso de cada mês do ano (1=janeiro): fim de ano forte, janeiro/fevereiro e julho fracos.
SAZONALIDADE = {1: 0.7, 2: 0.65, 3: 1.0, 4: 1.0, 5: 1.1, 6: 1.0, 7: 0.75, 8: 1.1, 9: 1.2, 10: 1.3, 11: 1.45, 12: 1.0}


def _sortear_dias_atras(rnd, hoje):
    """Quantos dias atrás cai o atendimento: 12 meses, mais movimento nos meses fortes e no período recente."""
    candidatos = list(range(-10, 366))
    pesos = [
        SAZONALIDADE[(hoje - timedelta(days=d)).month] * (1 + 0.4 * (365 - max(d, 0)) / 365)
        for d in candidatos
    ]
    return rnd.choices(candidatos, weights=pesos)[0]


def _escolher_status(rnd, dias_atras):
    if dias_atras < 0:  # data futura
        return rnd.choice([Status.SOLICITADO, Status.AGENDADO])
    if dias_atras > 60:  # histórico antigo: tudo resolvido
        return rnd.choices([Status.CONCLUIDO, Status.CANCELADO], weights=[87, 13])[0]
    if dias_atras <= 7:
        return rnd.choices(
            [Status.SOLICITADO, Status.AGENDADO, Status.EM_ANDAMENTO, Status.CONCLUIDO, Status.CANCELADO],
            weights=[10, 20, 20, 45, 5])[0]
    return rnd.choices([Status.CONCLUIDO, Status.CANCELADO, Status.EM_ANDAMENTO], weights=[80, 15, 5])[0]


def _etapas(rnd, status):
    """Sequência de status percorrida até chegar ao status final."""
    if status == Status.SOLICITADO:
        return []
    if status == Status.CANCELADO:
        return [Status.CANCELADO]
    etapas = [Status.AGENDADO] if (status == Status.AGENDADO or rnd.random() < 0.6) else []
    if status in (Status.EM_ANDAMENTO, Status.CONCLUIDO):
        etapas.append(Status.EM_ANDAMENTO)
    if status == Status.CONCLUIDO:
        etapas.append(Status.CONCLUIDO)
    return etapas


def _escolher_pagamento(rnd, status, dias_atras):
    if status == Status.CONCLUIDO:
        pesos = [93, 3, 4] if dias_atras > 60 else [70, 15, 15]  # o antigo quase todo já foi pago
        return rnd.choices([Sit.PAGO, Sit.PARCIAL, Sit.PENDENTE], weights=pesos)[0]
    if status in (Status.AGENDADO, Status.EM_ANDAMENTO):
        return rnd.choices([Sit.PENDENTE, Sit.PARCIAL], weights=[85, 15])[0]
    return Sit.PENDENTE


def _plano_recebimentos(rnd, situacao, final, primeira_data, hoje, formas):
    """
    Recebimentos coerentes com a situação sorteada: lista de (valor, data, forma, observação).
    Pago: à vista (70%) ou parcelado em 2-3 vezes de 30 em 30 dias no cartão de crédito; parcelas que
    ainda cairiam no futuro ficam por receber (o atendimento fica Parcial). Parcial: entrada de metade.
    """
    if situacao == Sit.PENDENTE or final <= 0:
        return []
    centavo = Decimal("0.01")
    if situacao == Sit.PARCIAL:
        return [((final / 2).quantize(centavo, ROUND_HALF_UP), primeira_data, rnd.choice(formas), "Entrada")]
    partes = 1 if rnd.random() < 0.7 else rnd.choice([2, 3])
    parcela = (final / partes).quantize(centavo, ROUND_HALF_UP)
    valores = [parcela] * (partes - 1) + [final - parcela * (partes - 1)]
    forma = rnd.choice(formas) if partes == 1 else FormaPagamento.CREDITO
    plano = []
    for k, valor in enumerate(valores):
        data = primeira_data + timedelta(days=30 * k)
        if data > hoje:
            break
        plano.append((valor, data, forma, "" if partes == 1 else f"Parcela {k + 1}/{partes}"))
    return plano


def gerar_atendimentos(usuarios, quantidade=320, refazer=False):
    """Retorna quantos atendimentos foram criados (0 se já existiam e refazer=False)."""
    if Atendimento.objects.exists():
        if not refazer:
            return 0
        # Agendamentos protegem o atendimento: saem primeiro (a agenda é refeita depois).
        from agenda.models import Agendamento
        Agendamento.objects.all().delete()
        # Recebimentos protegem o atendimento: saem primeiro (junto com a auditoria deles).
        Recebimento.objects.all().delete()
        RegistroAuditoria.objects.filter(entidade=RegistroAuditoria.Entidade.RECEBIMENTO).delete()
        Atendimento.objects.all().delete()  # o histórico é apagado junto (cascade)

    rnd = random.Random(2026)  # mesma semente = mesmos dados a cada execução
    tz = timezone.get_current_timezone()
    agora = timezone.now()
    hoje = timezone.localdate()

    servicos = list(TipoServico.objects.filter(ativo=True))
    veiculos = list(Veiculo.objects.all())
    alunos = list(Aluno.objects.select_related("cliente"))
    clientes = list(Cliente.objects.all())
    formas = [f for f, _ in FormaPagamento.choices]
    # Do 6º cliente em diante, cada um "chega" mais tarde (há quantos dias fez o 1º serviço):
    # assim existem clientes NOVOS em vários períodos do dashboard.
    cliente_desde = {c.pk: 330 - (i - 5) * 45 for i, c in enumerate(sorted(clientes, key=lambda c: c.pk)) if i >= 5}
    if not (servicos and veiculos and alunos and clientes):
        return 0

    recebimentos = []
    for _ in range(quantidade):
        dias_atras = _sortear_dias_atras(rnd, hoje)
        data = hoje - timedelta(days=dias_atras)
        tipo = rnd.choice(servicos)

        if Atendimento.categoria_exige_aluno(tipo.categoria):
            aluno = rnd.choice(alunos)
            cliente, veiculo = (aluno.cliente or rnd.choice(clientes)), None
        else:
            # pesos decrescentes: os primeiros veículos (clientes) voltam mais vezes = recorrentes
            aluno, veiculo = None, rnd.choices(veiculos, weights=[1 / (i + 1) ** 0.7 for i in range(len(veiculos))])[0]
            cliente = veiculo.proprietario

        desde = cliente_desde.get(cliente.pk)
        if desde is not None and dias_atras > desde:
            dias_atras = rnd.randint(-10, desde)
            data = hoje - timedelta(days=dias_atras)

        valor = tipo.valor_padrao
        desconto = Decimal(rnd.choice([0, 0, 0, 0, 10, 20, 30])) if valor >= 100 else Decimal(0)
        final = valor - desconto

        status = _escolher_status(rnd, dias_atras)
        etapas = _etapas(rnd, status)
        situacao = _escolher_pagamento(rnd, status, dias_atras)
        usuario = rnd.choice(usuarios)

        # Linha do tempo: criação 1–2 dias antes da data e uma etapa a cada algumas horas.
        criado = min(datetime.combine(data - timedelta(days=rnd.randint(1, 2)), time(9, 0), tz), agora)
        momentos = [min(criado + timedelta(hours=rnd.randint(3, 30) * (i + 1)), agora) for i in range(len(etapas))]
        fim = momentos[-1] if momentos else criado
        primeira_data = min(max(fim.astimezone(tz).date(), data), hoje)
        plano = _plano_recebimentos(rnd, situacao, final, primeira_data, hoje, formas)
        valor_pago = sum((v for v, *_ in plano), Decimal("0.00"))
        situacao = Sit.PAGO if (plano and valor_pago >= final) else (Sit.PARCIAL if plano else Sit.PENDENTE)

        a = Atendimento.objects.create(
            cliente=cliente, tipo_servico=tipo, veiculo=veiculo, aluno=aluno, data_atendimento=data,
            valor_cobrado=valor, desconto=desconto, situacao_pagamento=situacao, valor_pago=valor_pago,
            status=status, observacoes=rnd.choice(OBSERVACOES), registrado_por=usuario,
        )
        recebimentos.extend(
            Recebimento(atendimento=a, valor=v, data=d, forma=f, observacao=obs, criado_por=usuario, alterado_por=usuario)
            for v, d, f, obs in plano)
        # criado_em/atualizado_em são automáticos; ajusta para as datas fictícias.
        Atendimento.objects.filter(pk=a.pk).update(criado_em=criado, atualizado_em=fim)

        linhas = [HistoricoAtendimento(
            atendimento=a, tipo=Tipo.CRIACAO, valor_novo="Atendimento criado (Solicitado)",
            usuario=usuario, data_hora=criado)]
        anterior = Status.SOLICITADO
        for etapa, momento in zip(etapas, momentos):
            linhas.append(HistoricoAtendimento(
                atendimento=a, tipo=Tipo.STATUS, usuario=rnd.choice(usuarios), data_hora=momento,
                valor_anterior=Status(anterior).label, valor_novo=Status(etapa).label))
            anterior = etapa
        if situacao != Sit.PENDENTE:
            momento = min(fim + timedelta(hours=rnd.randint(1, 48)), agora)
            linhas.append(HistoricoAtendimento(
                atendimento=a, tipo=Tipo.PAGAMENTO, usuario=rnd.choice(usuarios), data_hora=momento,
                valor_anterior="Pendente", valor_novo=historico.estado(a)["pagamento"]))
        HistoricoAtendimento.objects.bulk_create(linhas)

    Recebimento.objects.bulk_create(recebimentos)
    return quantidade
