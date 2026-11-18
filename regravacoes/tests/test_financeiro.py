from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import Atendimento
from cadastros.models import Veiculo
from financeiro import regras as financeiro
from financeiro.models import Recebimento
from regravacoes import regras
from regravacoes.models import ConfiguracaoEmpresa, RegistroRegravacao

from .base import BaseRegravacaoTest

D = Decimal


class LancamentoNoFinanceiroTest(BaseRegravacaoTest):
    def concluir(self, r, usuario=None, **extra):
        self.client.force_login(usuario or self.admin)
        dados = {"data_concluida": self.dias(-1).isoformat(), "tecnico": self.tecnico.pk, "situacao": "recebido",
                 "forma": "pix", "data_recebimento": self.dias(0).isoformat()}
        dados.update(extra)
        return self.client.post(reverse("regravacao_concluir", args=[r.pk]), dados, follow=True)

    def test_concluida_e_recebida_cria_exatamente_um_atendimento_e_um_recebimento(self):
        r = self.registro(servico_motor=False, servico_chassi=True, valor=D("400.00"))
        resposta = self.concluir(r, forma="cartao_credito")
        self.assertContains(resposta, "Lançada no Financeiro")
        r.refresh_from_db()
        self.assertTrue(r.lancado)
        (a,) = Atendimento.objects.all()
        self.assertEqual((a.cliente, a.tipo_servico, a.status, a.situacao_pagamento), (self.cliente, self.srv_chassi, "concluido", "pago"))
        self.assertEqual((a.valor_cobrado, a.valor_pago, a.data_atendimento), (D("400.00"), D("400.00"), self.dias(-1)))
        (rec,) = Recebimento.objects.all()
        self.assertEqual((rec.atendimento, rec.valor, rec.forma, rec.data), (a, D("400.00"), "cartao_credito", self.dias(0)))
        self.assertEqual(r.atendimento, a)
        self.assertEqual(a.registro_regravacao, r)                             # vínculo de volta ao registro
        self.assertTrue(r.historico.filter(tipo="financeiro").exists())

    def test_tipo_de_servico_conforme_motor_chassi_ou_ambos(self):
        for i, (m, c, srv) in enumerate(((True, False, self.srv_motor), (False, True, self.srv_chassi), (True, True, self.srv_ambos))):
            r = self.registro(servico_motor=m, servico_chassi=c, placa=f"TIP{i}A23")
            self.concluir(r)
            r.refresh_from_db()
            self.assertEqual(r.atendimento.tipo_servico, srv)
            self.assertEqual(r.atendimento.tipo_servico.categoria, "regravacao")     # o Dashboard conta em Regravação

    def test_aparece_no_financeiro_e_no_dashboard(self):
        r = self.registro(valor=D("400.00"))
        self.concluir(r)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("recebimento_lista")), self.cliente.nome)
        self.assertContains(self.client.get(reverse("dashboard")), "Regravação")
        self.assertEqual(self.client.get(reverse("financeiro")).status_code, 200)

    def test_cria_o_veiculo_se_nao_existir_e_reaproveita_se_existir(self):
        r = self.registro(placa="NOV9A99", marca="Kia", modelo="Cerato", ano_modelo="2010/2011", cor="azul")
        self.concluir(r)
        v = Veiculo.objects.get(placa="NOV9A99")
        self.assertEqual((v.proprietario, v.marca, v.ano), (self.cliente, "Kia", 2011))
        existente = self.registro(placa=self.veiculo_outro.placa)
        self.concluir(existente)
        self.veiculo_outro.refresh_from_db()
        self.assertEqual(self.veiculo_outro.proprietario, self.outro_cliente)            # dono intocado
        existente.refresh_from_db()
        self.assertEqual(existente.atendimento.veiculo, self.veiculo_outro)

    def test_so_concluida_ou_so_recebida_nao_lanca(self):
        r = self.registro()
        self.concluir(r, situacao="pendente")
        self.assertEqual((Recebimento.objects.count(), RegistroRegravacao.objects.get().lancado), (0, False))
        r2 = self.registro(placa="REC2A23")
        self.concluir(r2, data_concluida="", tecnico="")                          # recebido, mas sem conclusão
        self.assertFalse(RegistroRegravacao.objects.get(pk=r2.pk).lancado)
        self.assertEqual(Recebimento.objects.count(), 0)

    def test_recebimento_marcado_depois_da_conclusao_lanca_nesse_momento_sem_duplicar(self):
        r = self.registro()
        self.concluir(r, situacao="pendente")
        self.assertEqual(Atendimento.objects.count(), 0)
        self.concluir(r, situacao="recebido")
        self.concluir(r, situacao="recebido")                                      # de novo / outra aba
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (1, 1))

    def test_concluir_ou_receber_duas_vezes_nao_duplica(self):
        r = self.registro()
        self.concluir(r)
        self.concluir(r)
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (1, 1))
        copia_antiga = RegistroRegravacao.objects.get(pk=r.pk)
        copia_antiga.lancado_em = None                                            # "outra aba" com tela desatualizada
        self.assertFalse(regras.lancar(copia_antiga, self.admin))                 # a trava no banco vence a tela velha
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (1, 1))

    def test_edicao_pelo_formulario_tambem_lanca_uma_vez(self):
        self.client.force_login(self.admin)
        dados = self.dados_form(data_agendada=self.dias(-3).isoformat(), data_concluida=self.dias(-1).isoformat(),
                                tecnico=self.tecnico.pk, recebimento_situacao="recebido", forma_pagamento="pix",
                                data_recebimento=self.dias(0).isoformat())
        self.client.post(reverse("regravacao_novo"), dados)
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (1, 1))

    def test_mes_fechado_bloqueia_e_nada_fica_gravado(self):
        hoje = timezone.localdate()
        mes = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
        financeiro.fechar_mes(mes, self.admin)
        r = self.registro()
        resposta = self.concluir(r, data_recebimento=mes.replace(day=10).isoformat(), data_concluida=mes.replace(day=9).isoformat())
        self.assertContains(resposta, f"O mês {mes:%m/%Y} está fechado")
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (0, 0))
        r.refresh_from_db()
        self.assertEqual((r.lancado, r.recebimento_situacao, r.data_concluida), (False, "pendente", None))   # tudo ou nada

    def test_forma_de_pagamento_obrigatoria(self):
        r = self.registro()
        resposta = self.concluir(r, forma="")
        self.assertContains(resposta, "Informe a forma de pagamento")
        self.assertEqual(Recebimento.objects.count(), 0)

    def test_sem_valor_ou_sem_tipo_de_servico_configurado_nao_lanca(self):
        sem_valor = self.registro(valor=None)
        self.assertContains(self.concluir(sem_valor), "Informe o valor")
        cfg = ConfiguracaoEmpresa.obter()
        cfg.servico_chassi = None
        cfg.save()
        self.assertContains(self.concluir(self.registro(placa="CFG1A23")), "aba Empresa")
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_nao_cria_atendimento_sem_dados_do_veiculo_para_cadastra_lo(self):
        r = self.registro(placa="SEM1A23", marca="", modelo="", ano_modelo="", cor="")
        self.assertContains(self.concluir(r), "preencha a marca, o modelo, o ano/modelo, a cor")
        self.assertEqual(Atendimento.objects.count(), 0)


class ReaberturaTest(BaseRegravacaoTest):
    def setUp(self):
        super().setUp()
        self.r = self.registro(valor=D("400.00"), data_concluida=self.dias(-1), tecnico=self.tecnico,
                               recebimento_situacao="recebido", forma_pagamento="pix", data_recebimento=self.dias(0))
        regras.lancar(self.r, self.admin)
        self.r.refresh_from_db()
        self.client.force_login(self.admin)

    def reabrir(self):
        return self.client.post(reverse("regravacao_reabrir", args=[self.r.pk]), follow=True)

    def test_reabrir_estorna_e_reabre_o_atendimento_sem_apagar_nada(self):
        self.assertContains(self.reabrir(), "Regravação reaberta")
        self.r.refresh_from_db()
        self.assertEqual((self.r.lancado, self.r.status, self.r.recebimento_situacao), (False, "agendada" if self.r.data_agendada else "solicitada", "pendente"))
        (rec,) = Recebimento.objects.all()
        self.assertIsNotNone(rec.estornado_em)
        self.assertIn("Reabertura da regravação", rec.motivo_estorno)
        a = self.r.atendimento
        a.refresh_from_db()
        self.assertEqual((a.status, a.situacao_pagamento, a.valor_pago), ("em_andamento", "pendente", D("0.00")))
        self.assertTrue(self.r.historico.filter(tipo="reabertura").exists())
        self.assertTrue(a.historico.filter(tipo="reabertura").exists())

    def test_concluir_de_novo_reaproveita_o_atendimento(self):
        self.reabrir()
        client_r = RegistroRegravacao.objects.get(pk=self.r.pk)
        regras.registrar_andamento(client_r, self.admin, data_concluida=self.dias(-1), tecnico=self.tecnico,
                                   situacao="recebido", forma="dinheiro", data_recebimento=self.dias(0))
        self.assertEqual(Atendimento.objects.count(), 1)
        self.assertEqual((Recebimento.objects.count(), Recebimento.objects.validos().count()), (2, 1))

    def test_nao_reabre_o_que_nao_esta_lancado(self):
        outra = self.registro(placa="NAO1A23")
        self.assertContains(self.client.post(reverse("regravacao_reabrir", args=[outra.pk]), follow=True), "não está lançada")

    def test_mes_fechado_bloqueia_a_reabertura(self):
        hoje = timezone.localdate()
        mes = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
        antiga = self.registro(placa="ANT1A23", data_concluida=mes.replace(day=9), tecnico=self.tecnico, recebimento_situacao="recebido",
                               forma_pagamento="pix", data_recebimento=mes.replace(day=10))
        regras.lancar(antiga, self.admin)
        financeiro.fechar_mes(mes, self.admin)
        self.assertContains(self.client.post(reverse("regravacao_reabrir", args=[antiga.pk]), follow=True), "está fechado")
        antiga.refresh_from_db()
        self.assertTrue(antiga.lancado)

    def test_lancada_fica_travada_e_nao_pode_ser_excluida(self):
        resposta = self.client.get(reverse("regravacao_editar", args=[self.r.pk]), follow=True)
        self.assertEqual(resposta.status_code, 200)                              # o Administrador (editar_lancada) edita
        self.assertContains(self.client.post(reverse("regravacao_excluir", args=[self.r.pk]), follow=True), "não pode ser excluída")
        self.assertTrue(RegistroRegravacao.objects.filter(pk=self.r.pk).exists())
        self.assertNotContains(self.client.get(self.r.get_absolute_url()), "Cancelar regravação")
