from datetime import timedelta

from django.core.exceptions import ValidationError
from django.urls import reverse

from agenda.models import Agendamento, HorarioFuncionamento

from .base import BaseAgendaTest, aware

S = Agendamento.Status


class HorarioTest(BaseAgendaTest):
    def _erros(self, **campos):
        ag = Agendamento(**campos)
        with self.assertRaises(ValidationError) as ctx:
            ag.full_clean()
        return ctx.exception.message_dict

    def test_fim_anterior_ao_inicio_e_recusado(self):
        erros = self._erros(atendimento=self.criar(), inicio=self.momento(11), fim=self.momento(10))
        self.assertIn("posterior ao horário de início", erros["fim"][0])

    def test_fim_igual_ao_inicio_e_recusado(self):
        erros = self._erros(atendimento=self.criar(), inicio=self.momento(10), fim=self.momento(10))
        self.assertIn("fim", erros)

    def test_local_outro_exige_detalhe(self):
        erros = self._erros(atendimento=self.criar(), inicio=self.momento(10), fim=self.momento(11), local="outro")
        self.assertIn("detalhe_local", erros)

    def test_nao_agenda_atendimento_concluido(self):
        erros = self._erros(atendimento=self.criar(status="concluido"), inicio=self.momento(10), fim=self.momento(11))
        self.assertIn("concluído ou cancelado", erros["atendimento"][0])

    def test_formulario_mostra_erro_em_portugues(self):
        self.client.force_login(self.func)
        resp = self.client.post(reverse("agendamento_novo"), self.dados_form(
            inicio="2030-01-07T11:00", fim="2030-01-07T10:00"))
        self.assertContains(resp, "O horário de fim deve ser posterior ao horário de início.")
        self.assertEqual(Agendamento.objects.count(), 0)
        resp = self.client.post(reverse("agendamento_novo"), {})
        self.assertContains(resp, "Selecione o atendimento.")
        self.assertContains(resp, "Informe o início.")

    def test_fim_em_branco_vira_uma_hora_depois(self):
        self.client.force_login(self.func)
        self.client.post(reverse("agendamento_novo"), self.dados_form(fim=""))
        ag = Agendamento.objects.get()
        self.assertEqual(ag.fim - ag.inicio, timedelta(hours=1))


class FusoTest(BaseAgendaTest):
    def test_horario_digitado_e_gravado_e_exibido_em_sao_paulo(self):
        self.client.force_login(self.func)
        self.client.post(reverse("agendamento_novo"), self.dados_form(
            inicio="2030-01-07T14:30", fim="2030-01-07T15:30"))
        ag = Agendamento.objects.get()
        # 14:30 em São Paulo (UTC-3) = 17:30 UTC
        self.assertEqual(ag.inicio.hour, 17)
        resp = self.client.get(ag.get_absolute_url())
        self.assertContains(resp, "07/01/2030 14:30")
        # e o campo de edição volta com o mesmo horário local
        resp = self.client.get(reverse("agendamento_editar", args=[ag.pk]))
        self.assertContains(resp, 'value="2030-01-07T14:30"')


class ConflitoTest(BaseAgendaTest):
    def setUp(self):
        self.client.force_login(self.func)
        self.existente = self.agendar(self.momento(10), responsavel=self.admin, local="cliente")

    def _post(self, **extra):
        return self.client.post(reverse("agendamento_novo"), self.dados_form(**extra))

    def test_conflito_do_mesmo_responsavel_avisa_e_nao_salva(self):
        resp = self._post(inicio="2030-01-07T10:30", fim="2030-01-07T11:30",
                          local="cliente", responsavel=self.admin.pk)
        self.assertEqual(Agendamento.objects.count(), 1)
        self.assertContains(resp, "conflita com 1 agendamento")
        self.assertContains(resp, "Salvar mesmo assim")
        self.assertContains(resp, self.existente.atendimento.cliente.nome)

    def test_usuario_pode_confirmar_e_salvar_mesmo_assim(self):
        self._post(inicio="2030-01-07T10:30", fim="2030-01-07T11:30", local="cliente",
                   responsavel=self.admin.pk, confirmar_conflito="on")
        self.assertEqual(Agendamento.objects.count(), 2)

    def test_conflito_do_local_da_empresa(self):
        self.agendar(self.momento(14), local="empresa")
        resp = self._post(inicio="2030-01-07T14:30", fim="2030-01-07T15:30", local="empresa")
        self.assertContains(resp, "conflita com 1 agendamento")

    def test_clientes_em_locais_diferentes_e_responsaveis_diferentes_nao_conflitam(self):
        self._post(inicio="2030-01-07T10:30", fim="2030-01-07T11:30", local="cliente", responsavel=self.func.pk)
        self.assertEqual(Agendamento.objects.count(), 2)

    def test_horarios_que_apenas_se_encostam_nao_conflitam(self):
        self._post(inicio="2030-01-07T11:00", fim="2030-01-07T12:00", local="cliente", responsavel=self.admin.pk)
        self.assertEqual(Agendamento.objects.count(), 2)

    def test_cancelado_nao_gera_conflito(self):
        self.existente.status = S.CANCELADO
        self.existente.save()
        self._post(inicio="2030-01-07T10:30", fim="2030-01-07T11:30", local="cliente", responsavel=self.admin.pk)
        self.assertEqual(Agendamento.objects.count(), 2)

    def test_editar_nao_conflita_consigo_mesmo(self):
        resp = self.client.post(reverse("agendamento_editar", args=[self.existente.pk]), self.dados_form(
            atendimento=self.existente.atendimento.pk, inicio="2030-01-07T10:15", fim="2030-01-07T11:00",
            local="cliente", responsavel=self.admin.pk))
        self.assertEqual(resp.status_code, 302)

    def test_metodo_conflitos_do_modelo(self):
        outro = Agendamento(inicio=self.momento(9, 30), fim=self.momento(10, 30), responsavel=self.admin, local="cliente")
        self.assertEqual(list(outro.conflitos()), [self.existente])


class ExpedienteTest(BaseAgendaTest):
    def setUp(self):
        self.client.force_login(self.func)

    def test_horario_padrao_foi_criado_pela_migracao(self):
        self.assertEqual(HorarioFuncionamento.objects.count(), 7)

    def test_dentro_do_expediente_nao_avisa(self):
        self.assertEqual(HorarioFuncionamento.aviso_para(self.momento(9), self.momento(10)), "")

    def test_fora_do_horario_avisa_e_permite_confirmar(self):
        resp = self.client.post(reverse("agendamento_novo"), self.dados_form(
            inicio="2030-01-07T19:00", fim="2030-01-07T20:00"))
        self.assertContains(resp, "Fora do horário de funcionamento (Segunda-feira: 08:00 às 18:00)")
        self.assertEqual(Agendamento.objects.count(), 0)
        self.client.post(reverse("agendamento_novo"), self.dados_form(
            inicio="2030-01-07T19:00", fim="2030-01-07T20:00", confirmar_conflito="on"))
        self.assertEqual(Agendamento.objects.count(), 1)

    def test_dia_fechado_avisa(self):
        domingo = aware(2030, 1, 6, 10)
        self.assertIn("não funciona", HorarioFuncionamento.aviso_para(domingo, domingo + timedelta(hours=1)))

    def test_administrador_edita_horario_e_funcionario_nao(self):
        self.assertEqual(self.client.get(reverse("agenda_horario")).status_code, 403)
        self.client.force_login(self.admin)
        formset = self.client.get(reverse("agenda_horario")).context["formset"]
        dados = {"form-TOTAL_FORMS": "7", "form-INITIAL_FORMS": "7", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000"}
        for i, form in enumerate(formset):
            h = form.instance
            dados[f"form-{i}-id"] = h.pk
            if h.aberto:
                dados[f"form-{i}-aberto"] = "on"
            dados[f"form-{i}-abre"] = "09:00" if h.dia_semana == 0 else (h.abre.strftime("%H:%M") if h.abre else "")
            dados[f"form-{i}-fecha"] = h.fecha.strftime("%H:%M") if h.fecha else ""
        resp = self.client.post(reverse("agenda_horario"), dados)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(HorarioFuncionamento.objects.get(dia_semana=0).abre.hour, 9)

    def test_horario_invalido_e_recusado(self):
        segunda = HorarioFuncionamento.objects.get(dia_semana=0)
        segunda.fecha = segunda.abre
        with self.assertRaises(ValidationError):
            segunda.full_clean()
