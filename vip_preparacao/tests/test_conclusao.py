from datetime import date, timedelta
from decimal import Decimal

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import Atendimento
from cadastros.models import Veiculo
from financeiro import regras as financeiro
from financeiro.models import Recebimento
from vip_preparacao import regras
from vip_preparacao.models import RegistroVip

from .base import BaseVipTest


def mensagens(resposta):
    return " ".join(str(m) for m in get_messages(resposta.wsgi_request))


class ConclusaoTest(BaseVipTest):
    def test_concluir_cria_um_atendimento_e_um_recebimento_com_os_valores_certos(self):
        r = self.registro(data_devolucao=self.dias(-2), valor=Decimal("150.00"))
        resposta = self.concluir(r, forma="cartao_credito")
        self.assertContains(resposta, "Registro concluído e recebimento lançado")
        r.refresh_from_db()
        self.assertEqual((r.status, r.concluido_por), ("concluido", self.admin))
        self.assertIsNotNone(r.concluido_em)

        self.assertEqual(Atendimento.objects.count(), 1)
        a = r.atendimento
        self.assertEqual((a.cliente, a.tipo_servico, a.status), (self.cliente, self.vip, "concluido"))
        self.assertEqual((a.valor_cobrado, a.desconto, a.valor_final), (Decimal("150.00"), Decimal("0.00"), Decimal("150.00")))
        self.assertEqual(a.data_atendimento, self.dias(-2))              # data de devolução
        self.assertEqual((a.situacao_pagamento, a.valor_pago), ("pago", Decimal("150.00")))
        (rec,) = Recebimento.objects.all()
        self.assertEqual((rec.atendimento, rec.valor, rec.forma, rec.data), (a, Decimal("150.00"), "cartao_credito", timezone.localdate()))
        self.assertEqual(rec.criado_por, self.admin)
        self.assertTrue(a.historico.filter(tipo="criacao").exists())
        self.assertTrue(r.historico.filter(tipo="conclusao").exists())

    def test_sem_data_de_devolucao_o_atendimento_usa_a_data_do_recebimento(self):
        r = self.registro()
        self.concluir(r, data=self.dias(-1).isoformat())
        r.refresh_from_db()
        self.assertEqual(r.atendimento.data_atendimento, self.dias(-1))

    def test_cria_o_veiculo_se_a_placa_nao_existe(self):
        r = self.registro(placa="NEW1A23", marca="Kia", modelo="Sportage", versao="EX", ano=2020, cor="outra", cor_outra="Grafite")
        self.concluir(r)
        v = Veiculo.objects.get(placa="NEW1A23")
        self.assertEqual((v.proprietario, v.marca, v.modelo, v.ano, v.cor), (self.cliente, "Kia", "Sportage EX", 2020, "Grafite"))
        r.refresh_from_db()
        self.assertEqual(r.atendimento.veiculo, v)

    def test_placa_ja_cadastrada_em_outro_cliente_nao_bloqueia_nem_muda_o_dono(self):
        """Um cliente pode ter vários carros e o carro não fica preso ao cliente do registro."""
        r = self.registro(placa=self.veiculo_outro.placa, cliente=self.cliente)
        resposta = self.concluir(r)
        self.assertContains(resposta, "Registro concluído")
        self.veiculo_outro.refresh_from_db()
        self.assertEqual(self.veiculo_outro.proprietario, self.outro_cliente)     # dono intocado
        r.refresh_from_db()
        self.assertEqual(r.atendimento.veiculo, self.veiculo_outro)
        self.assertEqual(Veiculo.objects.filter(placa=self.veiculo_outro.placa).count(), 1)

    def test_concluir_exige_marca_modelo_ano_e_cor(self):
        r = self.registro(marca="", modelo="", ano=None, cor="")
        resposta = self.concluir(r)
        self.assertContains(resposta, "preencha a marca, o modelo, o ano, a cor")
        r.refresh_from_db()
        self.assertEqual((r.status, Recebimento.objects.count(), Atendimento.objects.count()), ("em_andamento", 0, 0))

    def test_cor_outra_sem_descricao_nao_conclui(self):
        r = self.registro(cor="outra", cor_outra="")
        self.assertContains(self.concluir(r), "a cor")
        self.assertEqual(Recebimento.objects.count(), 0)

    def test_forma_de_pagamento_e_obrigatoria(self):
        r = self.registro()
        resposta = self.concluir(r, forma="")
        self.assertContains(resposta, "Informe a forma de pagamento")
        self.assertEqual(Recebimento.objects.count(), 0)

    def test_valor_zero_nao_gera_recebimento(self):
        r = self.registro(valor=Decimal("0.00"))
        self.assertContains(self.concluir(r), "maior que zero")
        self.assertEqual(RegistroVip.objects.get().status, "em_andamento")

    def test_recebimento_no_futuro_e_recusado_e_nada_fica_gravado(self):
        r = self.registro()
        resposta = self.concluir(r, data=self.dias(3).isoformat())
        self.assertContains(resposta, "não pode ser no futuro")
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count(), Veiculo.objects.filter(placa=r.placa).count()), (0, 0, 0))
        self.assertEqual(RegistroVip.objects.get().status, "em_andamento")

    def test_aparece_no_financeiro_e_no_historico_do_cliente(self):
        r = self.registro()
        self.concluir(r)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("recebimento_lista")), self.cliente.nome)
        self.assertContains(self.client.get(self.cliente.get_absolute_url()), "VIP completo")


class IdempotenciaTest(BaseVipTest):
    def test_concluir_duas_vezes_pela_view_gera_um_so_recebimento(self):
        r = self.registro()
        primeira = self.concluir(r)
        segunda = self.concluir(r)
        self.assertContains(primeira, "Registro concluído")
        self.assertContains(segunda, "já foi concluído")
        self.assertEqual((Recebimento.objects.count(), Atendimento.objects.count()), (1, 1))

    def test_concluir_duas_vezes_pela_regra_levanta_erro(self):
        r = self.registro()
        regras.concluir(r, None, "pix", date.today(), self.admin, False)
        copia_antiga = RegistroVip.objects.get(pk=r.pk)
        copia_antiga.status = "em_andamento"            # "outra aba" com a tela desatualizada
        with self.assertRaises(ValidationError):
            regras.concluir(copia_antiga, None, "pix", date.today(), self.admin, False)
        self.assertEqual(Recebimento.objects.count(), 1)

    def test_atendimento_e_unico_por_registro(self):
        r = self.registro()
        self.concluir(r)
        r.refresh_from_db()
        outro = self.registro(placa="OUT1A23")
        from django.db import IntegrityError, transaction
        outro.atendimento = r.atendimento
        with self.assertRaises(IntegrityError), transaction.atomic():
            outro.save()


class MesFechadoTest(BaseVipTest):
    def _fechar_mes_passado(self):
        hoje = timezone.localdate()
        mes_passado = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
        financeiro.fechar_mes(mes_passado, self.admin)
        return mes_passado

    def test_mes_fechado_bloqueia_a_conclusao(self):
        mes = self._fechar_mes_passado()
        r = self.registro()
        resposta = self.concluir(r, data=mes.replace(day=15).isoformat())
        self.assertContains(resposta, f"O mês {mes:%m/%Y} está fechado")
        self.assertEqual((Recebimento.objects.count(), Atendimento.objects.count()), (0, 0))
        self.assertEqual(RegistroVip.objects.get().status, "em_andamento")

    def test_mes_fechado_bloqueia_a_reabertura(self):
        mes = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
        r = self.registro()
        regras.concluir(r, None, "pix", mes.replace(day=10), self.admin, False)   # concluído com o mês ainda aberto
        financeiro.fechar_mes(mes, self.admin)
        self.client.force_login(self.admin)
        resposta = self.client.post(reverse("vip_reabrir", args=[r.pk]), follow=True)
        self.assertContains(resposta, "está fechado")
        r.refresh_from_db()
        self.assertEqual(r.status, "concluido")
        self.assertEqual(Recebimento.objects.validos().count(), 1)


class ReaberturaTest(BaseVipTest):
    def test_reabrir_estorna_o_recebimento_e_reabre_o_atendimento(self):
        r = self.registro()
        self.concluir(r)
        self.client.force_login(self.admin)
        resposta = self.client.post(reverse("vip_reabrir", args=[r.pk]), follow=True)
        self.assertContains(resposta, "Registro reaberto")
        r.refresh_from_db()
        self.assertEqual((r.status, r.concluido_em, r.concluido_por), ("em_andamento", None, None))
        (rec,) = Recebimento.objects.all()            # nunca apagado em silêncio
        self.assertIsNotNone(rec.estornado_em)
        self.assertIn(f"Reabertura do registro VIP/Preparação #{r.pk}", rec.motivo_estorno)
        a = r.atendimento
        a.refresh_from_db()
        self.assertEqual((a.status, a.situacao_pagamento, a.valor_pago), ("em_andamento", "pendente", Decimal("0.00")))
        self.assertEqual(r.historico.filter(tipo="reabertura").count(), 1)
        self.assertTrue(a.historico.filter(tipo="reabertura").exists())

    def test_concluir_de_novo_reaproveita_o_atendimento(self):
        r = self.registro()
        self.concluir(r)
        self.client.force_login(self.admin)
        self.client.post(reverse("vip_reabrir", args=[r.pk]))
        self.concluir(r, forma="dinheiro", valor="140.00")
        r.refresh_from_db()
        self.assertEqual(Atendimento.objects.count(), 1)
        self.assertEqual((Recebimento.objects.count(), Recebimento.objects.validos().count()), (2, 1))
        self.assertEqual((r.valor, r.atendimento.valor_pago, r.atendimento.status), (Decimal("140.00"), Decimal("140.00"), "concluido"))

    def test_nao_reabre_o_que_nao_esta_concluido(self):
        r = self.registro()
        self.client.force_login(self.admin)
        self.assertContains(self.client.post(reverse("vip_reabrir", args=[r.pk]), follow=True), "não está concluído")


class ValorNaConclusaoTest(BaseVipTest):
    def test_funcionario_conclui_mas_nao_altera_o_valor(self):
        r = self.registro(valor=Decimal("150.00"))
        self.concluir(r, usuario=self.func, valor="1.00")
        r.refresh_from_db()
        self.assertEqual((r.valor, r.atendimento.valor_cobrado), (Decimal("150.00"), Decimal("150.00")))
        self.assertEqual(Recebimento.objects.get().criado_por, self.func)

    def test_administrador_altera_o_valor_e_isso_fica_no_historico(self):
        r = self.registro(valor=Decimal("150.00"))
        self.concluir(r, valor="120.00")
        r.refresh_from_db()
        self.assertEqual((r.valor, Recebimento.objects.get().valor), (Decimal("120.00"), Decimal("120.00")))
        self.assertIn("valor alterado de R$ 150,00", r.historico.get(tipo="conclusao").valor_novo)
