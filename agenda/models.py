from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import Atendimento


def limites_do_dia(dia):
    """Início (inclusive) e fim (exclusive) do dia no fuso do projeto, como datetimes com fuso."""
    inicio = timezone.make_aware(datetime.combine(dia, time.min), timezone.get_current_timezone())
    return inicio, inicio + timedelta(days=1)


class AgendamentoQuerySet(models.QuerySet):
    def com_detalhes(self):
        """Traz de uma vez o que as telas mostram (evita uma consulta por linha)."""
        return self.select_related(
            "atendimento__cliente", "atendimento__tipo_servico",
            "atendimento__veiculo", "atendimento__aluno", "responsavel",
        )

    def ativos(self):
        return self.filter(status__in=Agendamento.ATIVOS)

    def do_dia(self, dia):
        ini, fim = limites_do_dia(dia)
        return self.filter(inicio__gte=ini, inicio__lt=fim)

    def hoje(self):
        """Agendamentos de hoje que ainda valem (ativos ou já concluídos)."""
        S = Agendamento.Status
        return self.do_dia(timezone.localdate()).filter(status__in=Agendamento.ATIVOS + [S.CONCLUIDO])

    def proximos_dias(self, dias=7):
        """Ativos de amanhã até daqui a `dias` dias (hoje fica em `hoje()`)."""
        ini, _ = limites_do_dia(timezone.localdate() + timedelta(days=1))
        return self.ativos().filter(inicio__gte=ini, inicio__lt=ini + timedelta(days=dias))

    def atrasados(self):
        """Sem baixa: ainda Agendado/Confirmado, mas o horário de fim já passou."""
        S = Agendamento.Status
        return self.filter(status__in=[S.AGENDADO, S.CONFIRMADO], fim__lt=timezone.now())

    def futuros(self):
        return self.ativos().filter(inicio__gte=timezone.now())


class Agendamento(models.Model):
    """Um horário marcado para um atendimento. Um atendimento pode ter vários (remarcações, aulas)."""

    class Status(models.TextChoices):
        AGENDADO = "agendado", "Agendado"
        CONFIRMADO = "confirmado", "Confirmado"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDO = "concluido", "Concluído"
        CANCELADO = "cancelado", "Cancelado"
        NAO_COMPARECEU = "nao_compareceu", "Não compareceu"
        REMARCADO = "remarcado", "Remarcado"

    class Local(models.TextChoices):
        EMPRESA = "empresa", "Na empresa"
        CLIENTE = "cliente", "No endereço do cliente"
        OUTRO = "outro", "Outro"

    # Ativos: ocupam o horário (contam para conflito e para "pendente").
    ATIVOS = [Status.AGENDADO, Status.CONFIRMADO, Status.EM_ANDAMENTO]
    # Depois de cancelado / não compareceu / remarcado, só o Administrador altera.
    TRAVADOS = [Status.CANCELADO, Status.NAO_COMPARECEU, Status.REMARCADO]

    # Botões rápidos: de qual status para quais. (Remarcar tem fluxo próprio.)
    TRANSICOES = {
        Status.AGENDADO: [Status.CONFIRMADO, Status.EM_ANDAMENTO, Status.CANCELADO, Status.NAO_COMPARECEU],
        Status.CONFIRMADO: [Status.EM_ANDAMENTO, Status.CANCELADO, Status.NAO_COMPARECEU],
        Status.EM_ANDAMENTO: [Status.CONCLUIDO, Status.CANCELADO],
        Status.CONCLUIDO: [],
        Status.CANCELADO: [Status.AGENDADO],       # reabrir (Administrador)
        Status.NAO_COMPARECEU: [Status.AGENDADO],  # reabrir (Administrador)
        Status.REMARCADO: [],
    }
    PODE_REMARCAR = [Status.AGENDADO, Status.CONFIRMADO]

    atendimento = models.ForeignKey(
        Atendimento, verbose_name="atendimento", on_delete=models.PROTECT, related_name="agendamentos",
    )
    inicio = models.DateTimeField("início")
    fim = models.DateTimeField("fim")
    local = models.CharField("local", max_length=10, choices=Local.choices, default=Local.EMPRESA)
    detalhe_local = models.CharField(
        "endereço / observação do local", max_length=200, blank=True,
        help_text="Obrigatório quando o local for “Outro”.",
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="responsável", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="agendamentos",
    )
    status = models.CharField("status", max_length=15, choices=Status.choices, default=Status.AGENDADO)
    observacoes = models.TextField("observações", blank=True)
    # Ao remarcar, o novo agendamento aponta para o antigo.
    remarcado_de = models.ForeignKey(
        "self", verbose_name="remarcado de", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="remarcacoes",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="criado por", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    objects = AgendamentoQuerySet.as_manager()

    class Meta:
        verbose_name = "agendamento"
        verbose_name_plural = "agendamentos"
        ordering = ["inicio", "id"]
        indexes = [models.Index(fields=["inicio"]), models.Index(fields=["status"])]
        permissions = [("reabrir", "Pode reabrir agendamento cancelado ou que não compareceu")]

    def __str__(self):
        return f"{self.atendimento} em {timezone.localtime(self.inicio):%d/%m/%Y %H:%M}"

    def get_absolute_url(self):
        return reverse("agendamento_detalhe", args=[self.pk])

    # ---------- Apoio ----------
    @property
    def ativo(self):
        return self.status in self.ATIVOS

    @property
    def travado(self):
        return self.status in self.TRAVADOS

    @property
    def atrasado(self):
        S = self.Status
        return self.status in (S.AGENDADO, S.CONFIRMADO) and self.fim < timezone.now()

    def pode_ir_para(self, novo):
        return novo in self.TRANSICOES.get(self.status, [])

    def conflitos(self):
        """
        Outros agendamentos ativos que se sobrepõem a este e dividem o responsável
        ou o local fixo da empresa. Horários que apenas se encostam (10h-11h e
        11h-12h) NÃO são conflito.
        """
        if self.status not in self.ATIVOS or not (self.inicio and self.fim):
            return Agendamento.objects.none()
        mesmo_recurso = Q()
        if self.responsavel_id:
            mesmo_recurso |= Q(responsavel_id=self.responsavel_id)
        if self.local == self.Local.EMPRESA:
            mesmo_recurso |= Q(local=self.Local.EMPRESA)
        if not mesmo_recurso:
            return Agendamento.objects.none()
        return (
            Agendamento.objects.com_detalhes()
            .ativos().filter(inicio__lt=self.fim, fim__gt=self.inicio)
            .filter(mesmo_recurso).exclude(pk=self.pk)
        )

    # ---------- Regras de negócio ----------
    def clean(self):
        erros = {}
        if self.inicio and self.fim and self.fim <= self.inicio:
            erros["fim"] = "O horário de fim deve ser posterior ao horário de início."
        if self.local == self.Local.OUTRO and not self.detalhe_local.strip():
            erros["detalhe_local"] = "Informe o endereço ou a observação do local."
        # Não se marca horário novo para um atendimento já concluído/cancelado.
        if self._state.adding and self.atendimento_id and self.atendimento.fechado:
            erros["atendimento"] = "Este atendimento está concluído ou cancelado e não aceita novos agendamentos."
        if erros:
            raise ValidationError(erros)


class HorarioFuncionamento(models.Model):
    """Dias e horários em que a empresa funciona (editável só pelo Administrador)."""

    class Dia(models.IntegerChoices):  # mesmo número do datetime.weekday()
        SEGUNDA = 0, "Segunda-feira"
        TERCA = 1, "Terça-feira"
        QUARTA = 2, "Quarta-feira"
        QUINTA = 3, "Quinta-feira"
        SEXTA = 4, "Sexta-feira"
        SABADO = 5, "Sábado"
        DOMINGO = 6, "Domingo"

    dia_semana = models.PositiveSmallIntegerField("dia da semana", choices=Dia.choices, unique=True)
    aberto = models.BooleanField("funciona neste dia", default=True)
    abre = models.TimeField("abre às", null=True, blank=True)
    fecha = models.TimeField("fecha às", null=True, blank=True)

    class Meta:
        verbose_name = "horário de funcionamento"
        verbose_name_plural = "horários de funcionamento"
        ordering = ["dia_semana"]

    def __str__(self):
        return self.get_dia_semana_display()

    def clean(self):
        if self.aberto:
            if not self.abre or not self.fecha:
                raise ValidationError("Informe o horário de abertura e de fechamento (ou desmarque “funciona neste dia”).")
            if self.fecha <= self.abre:
                raise ValidationError({"fecha": "O horário de fechamento deve ser depois do de abertura."})

    @classmethod
    def aviso_para(cls, inicio, fim):
        """Texto de aviso se o intervalo cair fora do expediente; "" se estiver tudo certo."""
        horarios = {h.dia_semana: h for h in cls.objects.all()}
        if not horarios or not inicio or not fim:
            return ""
        ini, fi = timezone.localtime(inicio), timezone.localtime(fim)
        h = horarios.get(ini.weekday())
        if h is None:
            return ""
        nome = h.get_dia_semana_display()
        if not h.aberto:
            return f"A empresa não funciona neste dia ({nome})."
        if ini.date() != fi.date() or ini.time() < h.abre or fi.time() > h.fecha:
            return f"Fora do horário de funcionamento ({nome}: {h.abre:%H:%M} às {h.fecha:%H:%M})."
        return ""
