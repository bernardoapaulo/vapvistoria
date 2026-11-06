import json
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from agenda.models import Agendamento
from atendimentos.models import Atendimento
from atendimentos.tests.base import BaseAtendimentoTest

from .base import BaseAgendaTest

S = Agendamento.Status


class PermissoesAgendaTest(BaseAgendaTest):
    def setUp(self):
        self.ag = self.agendar()

    def _status(self, url, usuario=None, metodo="get", dados=None):
        self.client.force_login(usuario or self.func)
        return getattr(self.client, metodo)(url, dados or {}).status_code

    def test_anonimo_vai_para_o_login(self):
        resp = self.client.get(reverse("agenda_calendario"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/entrar/", resp.url)

    def test_funcionario_ve_a_agenda_de_todos(self):
        outro = self.agendar(self.momento(15), responsavel=self.admin)
        self.client.force_login(self.func)
        for nome in ("agenda_calendario", "agendamento_lista", "agenda_pendencias"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200)
        self.assertContains(self.client.get(reverse("agendamento_lista")), outro.atendimento.cliente.nome)
        self.assertEqual(self.client.get(outro.get_absolute_url()).status_code, 200)

    def test_funcionario_cria_edita_e_muda_status(self):
        self.client.force_login(self.func)
        self.assertEqual(self.client.post(reverse("agendamento_novo"), self.dados_form(
            inicio="2030-01-07T14:00", fim="2030-01-07T15:00")).status_code, 302)
        self.assertEqual(self.client.get(reverse("agendamento_editar", args=[self.ag.pk])).status_code, 200)
        self.client.post(reverse("agendamento_status", args=[self.ag.pk, "confirmado"]))
        self.ag.refresh_from_db()
        self.assertEqual(self.ag.status, S.CONFIRMADO)

    def test_funcionario_nao_exclui(self):
        self.assertEqual(self._status(reverse("agendamento_excluir", args=[self.ag.pk])), 403)
        self.assertEqual(self._status(reverse("agendamento_excluir", args=[self.ag.pk]), metodo="post"), 403)
        self.assertTrue(Agendamento.objects.filter(pk=self.ag.pk).exists())
        html = self.client.get(self.ag.get_absolute_url()).content.decode()
        self.assertNotIn(reverse("agendamento_excluir", args=[self.ag.pk]), html)

    def test_administrador_exclui(self):
        self.assertEqual(self._status(reverse("agendamento_excluir", args=[self.ag.pk]), self.admin, "post"), 302)
        self.assertFalse(Agendamento.objects.exists())

    def test_cancelado_e_nao_compareceu_so_o_administrador_altera(self):
        for status in (S.CANCELADO, S.NAO_COMPARECEU, S.REMARCADO):
            self.ag.status = status
            self.ag.save()
            self.client.force_login(self.func)
            self.assertEqual(self.client.get(reverse("agendamento_editar", args=[self.ag.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("agendamento_editar", args=[self.ag.pk]), self.dados_form(
                atendimento=self.ag.atendimento.pk)).status_code, 403)
            self.assertEqual(self.client.post(reverse("agendamento_status", args=[self.ag.pk, "agendado"])).status_code, 403)
            html = self.client.get(self.ag.get_absolute_url()).content.decode()
            self.assertNotIn(reverse("agendamento_editar", args=[self.ag.pk]), html)
            self.assertNotIn("Reabrir", html)
            self.client.force_login(self.admin)
            self.assertEqual(self.client.get(reverse("agendamento_editar", args=[self.ag.pk])).status_code, 200)

    def test_administrador_reabre_cancelado(self):
        self.ag.status = S.CANCELADO
        self.ag.save()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.ag.get_absolute_url()), "Reabrir")
        self.client.post(reverse("agendamento_status", args=[self.ag.pk, "agendado"]))
        self.ag.refresh_from_db()
        self.assertEqual(self.ag.status, S.AGENDADO)

    def test_status_so_aceita_post(self):
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("agendamento_status", args=[self.ag.pk, "confirmado"])).status_code, 405)

    def test_nao_agenda_atendimento_concluido_pelo_formulario(self):
        self.client.force_login(self.func)
        concluido = self.criar(status="concluido")
        resp = self.client.post(reverse("agendamento_novo"), self.dados_form(atendimento=concluido.pk))
        self.assertEqual(resp.status_code, 200)  # a opção nem existe na lista
        self.assertEqual(Agendamento.objects.count(), 1)

    def test_menu_mostra_agenda(self):
        self.client.force_login(self.func)
        self.assertContains(self.client.get(reverse("inicio")), reverse("agenda_calendario"))


class ListaEFiltrosTest(BaseAgendaTest):
    def setUp(self):
        self.client.force_login(self.func)
        self.a1 = self.agendar(self.momento(9), responsavel=self.admin, local="empresa")
        self.a2 = self.agendar(self.momento(10, dia=(2030, 1, 20)), responsavel=self.func, local="cliente",
                               atendimento=self.criar(tipo_servico=self.limpeza), status=S.CONCLUIDO)
        self.a3 = self.agendar(self.momento(11), atendimento=self.criar(
            cliente=self.outro_cliente, veiculo=self.veiculo_outro), status=S.CANCELADO)

    def _ids(self, **filtros):
        resp = self.client.get(reverse("agendamento_lista"), filtros)
        self.assertEqual(resp.status_code, 200)
        return {g.pk for g in resp.context["object_list"]}

    def test_filtros(self):
        self.assertEqual(self._ids(), {self.a1.pk, self.a2.pk, self.a3.pk})
        self.assertEqual(self._ids(status="concluido"), {self.a2.pk})
        self.assertEqual(self._ids(responsavel=self.admin.pk), {self.a1.pk})
        self.assertEqual(self._ids(categoria="limpeza"), {self.a2.pk})
        self.assertEqual(self._ids(local="cliente"), {self.a2.pk})
        self.assertEqual(self._ids(de="2030-01-15"), {self.a2.pk})
        self.assertEqual(self._ids(ate="2030-01-07"), {self.a1.pk, self.a3.pk})
        self.assertEqual(self._ids(de="2030-01-07", ate="2030-01-07"), {self.a1.pk, self.a3.pk})

    def test_busca_e_valores_invalidos(self):
        self.assertEqual(self._ids(q="João"), {self.a3.pk})
        self.assertEqual(self._ids(q="XYZ9876"), {self.a3.pk})
        self.assertEqual(len(self._ids(status="xx", de="lixo", responsavel="abc", local="y")), 3)

    def test_paginacao_preserva_filtros(self):
        for i in range(16):
            self.agendar(self.momento(8, i), status=S.CONFIRMADO)
        resp = self.client.get(reverse("agendamento_lista"), {"status": "confirmado"})
        self.assertEqual(len(resp.context["object_list"]), 15)
        self.assertContains(resp, "status=confirmado&page=2")


class CalendarioTest(BaseAgendaTest):
    def setUp(self):
        self.client.force_login(self.func)

    def _eventos(self, inicio="2030-01-01T00:00:00-03:00", fim="2030-02-01T00:00:00-03:00"):
        resp = self.client.get(reverse("agenda_eventos"), {"start": inicio, "end": fim})
        self.assertEqual(resp.status_code, 200)
        return json.loads(resp.content)

    def test_evento_traz_horario_servico_cliente_e_cor_por_status(self):
        ag = self.agendar(self.momento(14, 30), status=S.CONFIRMADO)
        (evento,) = self._eventos()
        self.assertEqual(evento["start"], "2030-01-07T14:30:00")  # hora local, sem fuso
        self.assertEqual(evento["end"], "2030-01-07T15:30:00")
        self.assertEqual(evento["title"], "Vistoria · Maria Teste")
        self.assertEqual(evento["url"], ag.get_absolute_url())
        self.assertIn("evento-status-confirmado", evento["classNames"])

    def test_evento_nao_expoe_dados_pessoais(self):
        self.cliente.telefone = "11987654321"
        self.cliente.cpf_cnpj = "52998224725"
        self.cliente.save()
        self.agendar(local="cliente", detalhe_local="Rua Fictícia, 99")
        bruto = self.client.get(reverse("agenda_eventos"), {"start": "2030-01-01T00:00:00-03:00", "end": "2030-02-01T00:00:00-03:00"}).content.decode()
        for sensivel in ("11987654321", "52998224725", "Rua Fictícia", "ABC1234", "telefone", "cpf"):
            self.assertNotIn(sensivel, bruto)

    def test_so_traz_eventos_do_periodo_pedido(self):
        self.agendar(self.momento(10))
        self.agendar(self.momento(10, dia=(2030, 3, 4)))
        self.assertEqual(len(self._eventos()), 1)

    def test_atrasado_ganha_classe_propria(self):
        passado = self.agendar(timezone.now() - timedelta(days=1), status=S.AGENDADO)
        self.assertTrue(passado.atrasado)
        agora = timezone.now()
        (evento,) = self._eventos((agora - timedelta(days=3)).isoformat(), (agora + timedelta(days=3)).isoformat())
        self.assertIn("evento-atrasado", evento["classNames"])

    def test_pagina_do_calendario_carrega_fullcalendar_e_script(self):
        html = self.client.get(reverse("agenda_calendario")).content.decode()
        self.assertIn("vendor/fullcalendar/index.global.min.js", html)
        self.assertIn("agenda_calendario.js", html)
        self.assertIn(f'data-eventos="{reverse("agenda_eventos")}"', html)

    def test_eventos_exigem_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("agenda_eventos")).status_code, 302)


class IntegracaoAtendimentoTest(BaseAgendaTest):
    def test_criar_atendimento_novo_volta_para_agendar(self):
        self.client.force_login(self.func)
        url = reverse("atendimento_novo") + "?agendar=1"
        resp = self.client.post(url, BaseAtendimentoTest.dados_form(self))
        at = Atendimento.objects.get()
        self.assertRedirects(resp, f"{reverse('agendamento_novo')}?atendimento={at.pk}")
        resp = self.client.get(resp.url)
        self.assertEqual(resp.context["form"].initial["atendimento"], str(at.pk))

    def test_formulario_oferece_link_para_criar_atendimento(self):
        self.client.force_login(self.func)
        self.assertContains(self.client.get(reverse("agendamento_novo")), "Criar um atendimento novo")

    def test_rotulo_do_atendimento_mostra_cliente_e_servico(self):
        at = self.criar()
        resp = self.client.get(reverse("agendamento_novo")) if self.client.login(username="func", password="x") else None
        self.assertContains(resp, f"#{at.pk} · Maria Teste — Vistoria (ABC1234)")
