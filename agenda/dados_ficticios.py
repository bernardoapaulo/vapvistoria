"""
Gera agendamentos FICTÍCIOS coerentes com os atendimentos existentes, para testar
calendário, pendências e avisos. Usado pelo comando `popular_dados`.

- Atendimentos já existentes ganham agendamentos conforme o status deles
  (concluído -> agendamento concluído, cancelado -> cancelado/não compareceu...).
- Atendimentos EXTRAS (marcados em "observações") cobrem hoje, os próximos dias,
  atrasados, um remarcado, dois conflitos de horário e um horário fora do expediente.
Nunca usa dados reais.
"""
import random
from datetime import datetime, time, timedelta

from django.utils import timezone

from atendimentos import historico
from atendimentos.models import Atendimento, HistoricoAtendimento
from cadastros.models import Aluno, Veiculo
from servicos.models import TipoServico

from .models import Agendamento
from .regras import quando

S = Agendamento.Status
L = Agendamento.Local
StatusAt = Atendimento.Status
MARCA = "[agenda fictícia]"  # identifica os atendimentos extras para poder refazê-los


def _apagar():
    Agendamento.objects.all().delete()
    HistoricoAtendimento.objects.filter(tipo=HistoricoAtendimento.Tipo.AGENDA).delete()
    Atendimento.objects.filter(observacoes__startswith=MARCA).delete()


def _momento(dia, hora, minuto=0):
    return timezone.make_aware(datetime.combine(dia, time(hora, minuto)), timezone.get_current_timezone())


def _local_para(rnd, tipo):
    if tipo.categoria == TipoServico.Categoria.CAPACITACAO:
        return L.EMPRESA, ""
    if tipo.categoria in (TipoServico.Categoria.LIMPEZA, TipoServico.Categoria.REPAROS):
        return rnd.choice([(L.CLIENTE, "Endereço informado pelo cliente (fictício)"), (L.EMPRESA, "")])
    return rnd.choice([(L.EMPRESA, ""), (L.EMPRESA, ""), (L.OUTRO, "Pátio parceiro (fictício)")])


class _Gerador:
    def __init__(self, usuarios):
        self.rnd = random.Random(2027)  # mesma semente = mesmos dados a cada execução
        self.usuarios = usuarios
        self.agora = timezone.now()
        self.hoje = timezone.localdate()
        self.historicos = []

    def criar(self, at, inicio, minutos, status, local=None, detalhe="", responsavel="sorteio",
              remarcado_de=None, criado=None):
        rnd = self.rnd
        if local is None:
            local, detalhe = _local_para(rnd, at.tipo_servico)
        if responsavel == "sorteio":
            responsavel = rnd.choice(self.usuarios + [None])
        criador = rnd.choice(self.usuarios)
        ag = Agendamento.objects.create(
            atendimento=at, inicio=inicio, fim=inicio + timedelta(minutes=minutos), local=local,
            detalhe_local=detalhe, responsavel=responsavel, status=status,
            remarcado_de=remarcado_de, criado_por=criador,
        )
        criado = min(criado or (inicio - timedelta(days=rnd.randint(1, 3))), self.agora)
        Agendamento.objects.filter(pk=ag.pk).update(criado_em=criado, atualizado_em=min(inicio, self.agora))
        self.historicos.append(HistoricoAtendimento(
            atendimento=at, tipo=HistoricoAtendimento.Tipo.AGENDA, usuario=criador, data_hora=criado,
            valor_novo=f"Agendamento criado para {quando(ag)}",
        ))
        return ag

    # ---------- atendimentos que já existiam ----------
    def para_existente(self, at):
        rnd = self.rnd
        minutos = 180 if at.tipo_servico.categoria == TipoServico.Categoria.CAPACITACAO else 60
        inicio = _momento(at.data_atendimento, rnd.randint(8, 16), rnd.choice([0, 30]))

        if at.status == StatusAt.CONCLUIDO:
            anterior = None
            sorteio = rnd.random()
            if sorteio < 0.15:    # foi remarcado uma vez
                anterior = self.criar(at, inicio - timedelta(days=2), minutos, S.REMARCADO)
            elif sorteio < 0.25:  # cliente faltou na primeira vez
                self.criar(at, inicio - timedelta(days=3), minutos, S.NAO_COMPARECEU)
            self.criar(at, inicio, minutos, S.CONCLUIDO, remarcado_de=anterior)
        elif at.status == StatusAt.CANCELADO:
            sorteio = rnd.random()
            if sorteio < 0.55:
                self.criar(at, inicio, minutos, S.CANCELADO)
            elif sorteio < 0.8:
                self.criar(at, inicio, minutos, S.NAO_COMPARECEU)
        elif at.status == StatusAt.EM_ANDAMENTO:
            self.criar(at, inicio, minutos, S.EM_ANDAMENTO)
        elif at.status == StatusAt.AGENDADO:
            # Data passada + ainda Agendado/Confirmado = atrasado (sem baixa).
            self.criar(at, inicio, minutos, rnd.choice([S.AGENDADO, S.CONFIRMADO]))
        # Solicitado: fica sem agendamento (aparece em "Solicitados sem agendamento").

    # ---------- atendimentos extras (hoje, futuro, atrasados, conflitos) ----------
    def novo_atendimento(self, status_final):
        rnd = self.rnd
        tipos = list(TipoServico.objects.filter(ativo=True).exclude(categoria=TipoServico.Categoria.CAPACITACAO))
        tipo = rnd.choice(tipos)
        veiculo = rnd.choice(list(Veiculo.objects.select_related("proprietario")))
        usuario = rnd.choice(self.usuarios)
        at = Atendimento.objects.create(
            cliente=veiculo.proprietario, tipo_servico=tipo, veiculo=veiculo, valor_cobrado=tipo.valor_padrao,
            data_atendimento=self.hoje, observacoes=MARCA, registrado_por=usuario,
        )
        historico.registrar_criacao(at, usuario)
        for etapa in ([StatusAt.AGENDADO] if status_final == StatusAt.AGENDADO else
                      [StatusAt.AGENDADO, StatusAt.EM_ANDAMENTO] if status_final == StatusAt.EM_ANDAMENTO else
                      [StatusAt.AGENDADO, StatusAt.EM_ANDAMENTO, StatusAt.CONCLUIDO]):
            historico.alterar_status(at, etapa, usuario)
        return at

    def extras(self):
        admin, func = self.usuarios[0], self.usuarios[-1]
        dia = lambda n: self.hoje + timedelta(days=n)  # noqa: E731
        E = L.EMPRESA
        # (dia, hora, min, duração, status do agendamento, status do atendimento, local, responsável)
        previstos = [
            # HOJE
            (0, 8, 0, 60, S.CONCLUIDO, StatusAt.CONCLUIDO, E, func),
            (0, 10, 0, 60, S.EM_ANDAMENTO, StatusAt.EM_ANDAMENTO, E, admin),
            (0, 10, 30, 60, S.AGENDADO, StatusAt.AGENDADO, L.CLIENTE, admin),      # CONFLITO: mesmo responsável
            (0, 15, 0, 90, S.CONFIRMADO, StatusAt.AGENDADO, E, func),
            # PRÓXIMOS DIAS
            (1, 9, 0, 60, S.AGENDADO, StatusAt.AGENDADO, E, func),
            (1, 9, 30, 60, S.CONFIRMADO, StatusAt.AGENDADO, E, admin),             # CONFLITO: local da empresa
            (2, 19, 0, 60, S.AGENDADO, StatusAt.AGENDADO, E, func),                # fora do expediente
            (3, 14, 0, 120, S.AGENDADO, StatusAt.AGENDADO, L.CLIENTE, None),
            (5, 10, 0, 60, S.AGENDADO, StatusAt.AGENDADO, E, admin),
            # ATRASADOS (passaram e ninguém deu baixa)
            (-1, 14, 0, 60, S.AGENDADO, StatusAt.AGENDADO, E, func),
            (-3, 9, 0, 60, S.CONFIRMADO, StatusAt.AGENDADO, L.CLIENTE, admin),
        ]
        for n, hora, minuto, duracao, status_ag, status_at, local, resp in previstos:
            at = self.novo_atendimento(status_at)
            detalhe = "Endereço informado pelo cliente (fictício)" if local == L.CLIENTE else ""
            Atendimento.objects.filter(pk=at.pk).update(data_atendimento=dia(n))
            self.criar(at, _momento(dia(n), hora, minuto), duracao, status_ag, local=local, detalhe=detalhe,
                       responsavel=resp, criado=self.agora - timedelta(days=2))

        # Um agendamento remarcado: o antigo ficou "Remarcado" e o novo aponta para ele.
        at = self.novo_atendimento(StatusAt.AGENDADO)
        antigo = self.criar(at, _momento(dia(-2), 11), 60, S.REMARCADO, local=E, responsavel=func,
                            criado=self.agora - timedelta(days=4))
        self.criar(at, _momento(dia(2), 11), 60, S.AGENDADO, local=E, responsavel=func,
                   remarcado_de=antigo, criado=self.agora - timedelta(days=1))


def gerar_agendamentos(usuarios, refazer=False):
    """Retorna quantos agendamentos foram criados (0 se já existiam e refazer=False)."""
    if Agendamento.objects.exists():
        if not refazer:
            return 0
        _apagar()
    if not (Atendimento.objects.exists() and Veiculo.objects.exists() and usuarios):
        return 0

    g = _Gerador(usuarios)
    existentes = (
        Atendimento.objects.exclude(observacoes__startswith=MARCA)
        .select_related("tipo_servico").order_by("id")
    )
    for at in existentes:
        g.para_existente(at)
    g.extras()
    HistoricoAtendimento.objects.bulk_create(g.historicos)
    return Agendamento.objects.count()
