from django.urls import reverse

from agenda import regras
from agenda.models import Agendamento
from atendimentos.models import Atendimento, HistoricoAtendimento

from .base import BaseAgendaTest

S = Agendamento.Status
SA = Atendimento.Status
Tipo = HistoricoAtendimento.Tipo


class SincronizacaoTest(BaseAgendaTest):
    def setUp(self):
        self.client.force_login(self.func)

    def _historico(self, atendimento, tipo):
        return list(atendimento.historico.filter(tipo=tipo))

    def test_criar_agendamento_move_atendimento_solicitado_para_agendado(self):
        at = self.criar(status="solicitado")
        self.client.post(reverse("agendamento_novo"), self.dados_form(atendimento=at.pk))
        at.refresh_from_db()
        self.assertEqual(at.status, SA.AGENDADO)
        mudanca = self._historico(at, Tipo.STATUS)[0]
        self.assertEqual((mudanca.valor_anterior, mudanca.valor_novo, mudanca.usuario), ("Solicitado", "Agendado", self.func))
        self.assertEqual(len(self._historico(at, Tipo.AGENDA)), 1)

    def test_criar_agendamento_nao_mexe_em_atendimento_que_nao_esta_solicitado(self):
        at = self.criar(status="em_andamento")
        self.client.post(reverse("agendamento_novo"), self.dados_form(atendimento=at.pk))
        at.refresh_from_db()
        self.assertEqual(at.status, SA.EM_ANDAMENTO)
        self.assertEqual(self._historico(at, Tipo.STATUS), [])

    def test_iniciar_agendamento_poe_atendimento_em_andamento(self):
        ag = self.agendar(atendimento=self.criar(status="agendado"))
        self.client.post(reverse("agendamento_status", args=[ag.pk, "em_andamento"]))
        ag.refresh_from_db()
        ag.atendimento.refresh_from_db()
        self.assertEqual(ag.status, S.EM_ANDAMENTO)
        self.assertEqual(ag.atendimento.status, SA.EM_ANDAMENTO)
        passos = [(h.valor_anterior, h.valor_novo) for h in self._historico(ag.atendimento, Tipo.STATUS)]
        self.assertEqual(passos, [("Agendado", "Em andamento")])

    def test_confirmar_nao_altera_atendimento(self):
        ag = self.agendar(atendimento=self.criar(status="agendado"))
        self.client.post(reverse("agendamento_status", args=[ag.pk, "confirmado"]))
        ag.refresh_from_db()
        ag.atendimento.refresh_from_db()
        self.assertEqual((ag.status, ag.atendimento.status), (S.CONFIRMADO, SA.AGENDADO))

    def test_concluir_pergunta_antes_de_concluir_o_atendimento(self):
        ag = self.agendar(atendimento=self.criar(status="em_andamento"), status=S.EM_ANDAMENTO)
        # o botão "Concluir" não conclui direto: leva para a pergunta
        resp = self.client.post(reverse("agendamento_status", args=[ag.pk, "concluido"]))
        self.assertRedirects(resp, reverse("agendamento_concluir", args=[ag.pk]))
        ag.refresh_from_db()
        self.assertEqual(ag.status, S.EM_ANDAMENTO)
        resp = self.client.get(reverse("agendamento_concluir", args=[ag.pk]))
        self.assertContains(resp, "Concluir também o atendimento")
        self.assertTrue(resp.context["marcado"])  # único agendamento: já vem marcado

    def test_concluir_somente_o_agendamento(self):
        ag = self.agendar(atendimento=self.criar(status="em_andamento"), status=S.EM_ANDAMENTO)
        self.client.post(reverse("agendamento_concluir", args=[ag.pk]), {})
        ag.refresh_from_db()
        ag.atendimento.refresh_from_db()
        self.assertEqual((ag.status, ag.atendimento.status), (S.CONCLUIDO, SA.EM_ANDAMENTO))

    def test_concluir_agendamento_e_atendimento_gera_historico(self):
        ag = self.agendar(atendimento=self.criar(status="em_andamento"), status=S.EM_ANDAMENTO)
        self.client.post(reverse("agendamento_concluir", args=[ag.pk]), {"concluir_atendimento": "on"})
        ag.atendimento.refresh_from_db()
        self.assertEqual(ag.atendimento.status, SA.CONCLUIDO)
        h = self._historico(ag.atendimento, Tipo.STATUS)[-1]
        self.assertEqual((h.valor_anterior, h.valor_novo, h.usuario), ("Em andamento", "Concluído", self.func))

    def test_pergunta_avisa_quando_ha_outros_agendamentos_pendentes(self):
        at = self.criar(status="em_andamento")
        ag = self.agendar(atendimento=at, status=S.EM_ANDAMENTO)
        self.agendar(self.momento(14), atendimento=at)
        resp = self.client.get(reverse("agendamento_concluir", args=[ag.pk]))
        self.assertEqual(resp.context["outros_ativos"], 1)
        self.assertFalse(resp.context["marcado"])
        self.assertContains(resp, "outro agendamento pendente")

    def test_cancelar_e_nao_compareceu_nao_alteram_o_atendimento(self):
        for destino in ("cancelado", "nao_compareceu"):
            ag = self.agendar(atendimento=self.criar(status="agendado"))
            self.client.post(reverse("agendamento_status", args=[ag.pk, destino]))
            ag.refresh_from_db()
            ag.atendimento.refresh_from_db()
            self.assertEqual(ag.status, destino)
            self.assertEqual(ag.atendimento.status, SA.AGENDADO)

    def test_transicao_invalida_e_recusada(self):
        ag = self.agendar(status=S.CONCLUIDO)
        with self.assertRaises(regras.RegraAgenda):
            regras.mudar_status(ag, S.CONFIRMADO, self.func)
        resp = self.client.post(reverse("agendamento_status", args=[ag.pk, "confirmado"]), follow=True)
        self.assertContains(resp, "não é permitida")

    def test_editar_horario_registra_no_historico_do_atendimento(self):
        ag = self.agendar()
        self.client.post(reverse("agendamento_editar", args=[ag.pk]), self.dados_form(
            atendimento=ag.atendimento.pk, inicio="2030-01-07T15:00", fim="2030-01-07T16:00"))
        textos = [h.valor_novo for h in self._historico(ag.atendimento, Tipo.AGENDA)]
        self.assertTrue(any("Horário alterado" in t for t in textos))

    def test_excluir_agendamento_pelo_administrador_registra_historico(self):
        self.client.force_login(self.admin)
        ag = self.agendar()
        at = ag.atendimento
        self.client.post(reverse("agendamento_excluir", args=[ag.pk]))
        self.assertFalse(Agendamento.objects.exists())
        self.assertTrue(any("excluído" in h.valor_novo for h in self._historico(at, Tipo.AGENDA)))


class RemarcacaoTest(BaseAgendaTest):
    def setUp(self):
        self.client.force_login(self.func)
        self.ag = self.agendar(atendimento=self.criar(status="agendado"), responsavel=self.func,
                               local="cliente", detalhe_local="Rua Fictícia, 1", observacoes="Trazer chave")

    def _remarcar(self, **extra):
        dados = {"inicio": "2030-01-08T09:00", "fim": "2030-01-08T10:00"}
        dados.update(extra)
        return self.client.post(reverse("agendamento_remarcar", args=[self.ag.pk]), dados)

    def test_remarcar_cria_novo_marca_antigo_e_liga_os_dois(self):
        resp = self._remarcar()
        novo = Agendamento.objects.exclude(pk=self.ag.pk).get()
        self.assertRedirects(resp, novo.get_absolute_url())
        self.ag.refresh_from_db()
        self.assertEqual(self.ag.status, S.REMARCADO)
        self.assertEqual(novo.status, S.AGENDADO)
        self.assertEqual(novo.remarcado_de, self.ag)
        self.assertEqual(list(self.ag.remarcacoes.all()), [novo])
        # mantém os dados do original
        self.assertEqual((novo.atendimento, novo.responsavel, novo.local, novo.detalhe_local, novo.observacoes),
                         (self.ag.atendimento, self.func, "cliente", "Rua Fictícia, 1", "Trazer chave"))

    def test_remarcar_registra_historico_e_mantem_atendimento_agendado(self):
        self._remarcar()
        self.ag.atendimento.refresh_from_db()
        self.assertEqual(self.ag.atendimento.status, SA.AGENDADO)
        textos = [h.valor_novo for h in self.ag.atendimento.historico.filter(tipo=Tipo.AGENDA)]
        self.assertTrue(any("remarcado de" in t for t in textos))

    def test_remarcar_para_horario_com_conflito_avisa(self):
        self.agendar(self.momento(9, dia=(2030, 1, 8)), responsavel=self.func, local="cliente")
        self._remarcar()
        self.assertEqual(Agendamento.objects.count(), 2)  # nada mudou: pediu confirmação
        resp = self._remarcar()
        self.assertContains(resp, "Salvar mesmo assim")
        self._remarcar(confirmar_conflito="on")
        self.assertEqual(Agendamento.objects.count(), 3)

    def test_remarcar_para_perto_do_horario_antigo_nao_conflita_com_ele(self):
        self._remarcar(inicio="2030-01-07T10:30", fim="2030-01-07T11:30")
        self.assertEqual(Agendamento.objects.count(), 2)

    def test_remarcar_valida_fim(self):
        resp = self._remarcar(inicio="2030-01-08T10:00", fim="2030-01-08T09:00")
        self.assertContains(resp, "posterior ao horário de início")
        self.assertEqual(Agendamento.objects.count(), 1)

    def test_nao_remarca_agendamento_em_andamento_ou_ja_remarcado(self):
        for status in (S.EM_ANDAMENTO, S.CONCLUIDO):
            self.ag.status = status
            self.ag.save()
            resp = self.client.get(reverse("agendamento_remarcar", args=[self.ag.pk]), follow=True)
            self.assertContains(resp, "Só é possível remarcar")
        self.ag.status = S.REMARCADO
        self.ag.save()
        self.assertEqual(self.client.get(reverse("agendamento_remarcar", args=[self.ag.pk])).status_code, 403)
