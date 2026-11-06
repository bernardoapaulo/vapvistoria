from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from agenda import consultas
from agenda.models import Agendamento

from .base import BaseAgendaTest

S = Agendamento.Status


class PendenciasTest(BaseAgendaTest):
    def setUp(self):
        self.agora = timezone.now()
        self.client.force_login(self.func)

    def _ids(self, qs):
        return {g.pk for g in qs}

    def test_atrasado_e_agendado_ou_confirmado_com_horario_ja_passado(self):
        atrasado1 = self.agendar(self.agora - timedelta(days=2), status=S.AGENDADO)
        atrasado2 = self.agendar(self.agora - timedelta(hours=3), status=S.CONFIRMADO)
        self.agendar(self.agora - timedelta(days=2), status=S.CONCLUIDO)
        self.agendar(self.agora - timedelta(days=2), status=S.CANCELADO)
        self.agendar(self.agora - timedelta(days=2), status=S.NAO_COMPARECEU)
        self.agendar(self.agora - timedelta(days=2), status=S.REMARCADO)
        self.agendar(self.agora - timedelta(days=2), status=S.EM_ANDAMENTO)
        self.agendar(self.agora + timedelta(hours=2), status=S.AGENDADO)  # futuro
        self.assertEqual(self._ids(Agendamento.objects.atrasados()), {atrasado1.pk, atrasado2.pk})
        self.assertTrue(atrasado1.atrasado)

    def test_agendamento_em_curso_nao_e_atrasado(self):
        em_curso = self.agendar(self.agora - timedelta(minutes=10), minutos=60, status=S.AGENDADO)
        self.assertFalse(em_curso.atrasado)
        self.assertEqual(self._ids(Agendamento.objects.atrasados()), set())

    def test_hoje_e_proximos_sete_dias(self):
        hoje = timezone.localdate()
        meio_dia = lambda n: self.momento(12, dia=(hoje + timedelta(days=n)).timetuple()[:3])  # noqa: E731
        de_hoje = self.agendar(meio_dia(0))
        concluido_hoje = self.agendar(meio_dia(0), status=S.CONCLUIDO)
        self.agendar(meio_dia(0), status=S.CANCELADO)
        amanha = self.agendar(meio_dia(1))
        dia7 = self.agendar(meio_dia(7))
        self.agendar(meio_dia(8))   # fora da janela
        self.agendar(meio_dia(-1))  # ontem
        self.assertEqual(self._ids(Agendamento.objects.hoje()), {de_hoje.pk, concluido_hoje.pk})
        self.assertEqual(self._ids(Agendamento.objects.proximos_dias(7)), {amanha.pk, dia7.pk})

    def test_solicitados_sem_agendamento(self):
        sem = self.criar(status="solicitado")
        com = self.criar(status="solicitado")
        self.agendar(atendimento=com)
        so_cancelado = self.criar(status="solicitado")
        self.agendar(atendimento=so_cancelado, status=S.CANCELADO)  # sem agendamento ativo: continua pendente
        self.criar(status="agendado")  # já não é "Solicitado"
        ids = {a.pk for a in consultas.solicitados_sem_agendamento()}
        self.assertEqual(ids, {sem.pk, so_cancelado.pk})

    def test_painel_mostra_as_quatro_secoes(self):
        self.agendar(self.agora - timedelta(days=1), status=S.AGENDADO)
        self.criar(status="solicitado")
        resp = self.client.get(reverse("agenda_pendencias"))
        for titulo in ("Atrasados", "Hoje", "Próximos 7 dias", "Solicitados sem agendamento"):
            self.assertContains(resp, titulo)
        self.assertEqual(len(resp.context["atrasados"]), 1)
        self.assertEqual(len(resp.context["sem_agendamento"]), 1)

    def test_contagem_na_pagina_inicial(self):
        self.agendar(self.agora - timedelta(days=1), status=S.AGENDADO)  # atrasado
        self.criar(status="solicitado")                                   # sem agendamento
        resp = self.client.get(reverse("inicio"))
        self.assertEqual(resp.context["total_pendencias"], 2)
        self.assertContains(resp, "Hoje")
        self.assertContains(resp, reverse("agenda_pendencias"))

    def test_bloco_hoje_lista_os_agendamentos_do_dia(self):
        hoje = timezone.localdate().timetuple()[:3]
        ag = self.agendar(self.momento(13, dia=hoje))
        resp = self.client.get(reverse("inicio"))
        self.assertContains(resp, ag.atendimento.cliente.nome)
        self.assertEqual(list(resp.context["agenda_hoje"]), [ag])

    def test_detalhes_do_atendimento_e_do_cliente(self):
        proximo = self.agendar(self.agora + timedelta(days=2))
        self.agendar(self.agora + timedelta(days=5), atendimento=proximo.atendimento)
        self.agendar(self.agora - timedelta(days=5), atendimento=proximo.atendimento)
        resp = self.client.get(proximo.atendimento.get_absolute_url())
        self.assertEqual(len(resp.context["agendamentos"]), 3)
        self.assertContains(resp, "Agendamentos")
        resp = self.client.get(reverse("cliente_detalhe", args=[self.cliente.pk]))
        self.assertEqual(resp.context["proximo_agendamento"], proximo)
        self.assertContains(resp, "Próximo agendamento")

    def test_consultas_da_agenda_usam_poucas_consultas(self):
        for i in range(10):
            self.agendar(self.agora + timedelta(hours=i + 1), responsavel=self.func)
        with self.assertNumQueries(7):  # sessão, usuário, permissões (2), total, responsáveis do filtro, agendamentos
            self.client.get(reverse("agendamento_lista"))
