from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.urls import reverse

from vip_preparacao.models import RegistroVip, validar_chassi

from .base import BaseVipTest


class ValidacaoDosDadosTest(BaseVipTest):
    def test_placa_e_normalizada_e_aceita_os_dois_formatos(self):
        for digitada, guardada in (("abc-1234", "ABC1234"), (" abc 1d23 ", "ABC1D23"), ("ABC1D23", "ABC1D23")):
            r = self.criar_pelo_form(placa=digitada)
            self.assertEqual(r.status_code, 302, digitada)
            self.assertTrue(RegistroVip.objects.filter(placa=guardada).exists(), guardada)

    def test_placa_invalida(self):
        r = self.criar_pelo_form(placa="AB12")
        self.assertContains(r, "Placa inválida")
        self.assertEqual(RegistroVip.objects.count(), 0)

    def test_chassi_17_caracteres_sem_i_o_q(self):
        validar_chassi("9bwzzz377vt004251")       # válido (minúsculas são aceitas e normalizadas no salvar)
        validar_chassi("")                        # opcional
        for ruim in ("9BWZZZ377VT00425", "9BWZZZ377VT0042511", "9BWZZZ377VT00425I", "9BWZZZ377VT00425O", "9BWZZZ377VT00425Q"):
            with self.assertRaises(ValidationError, msg=ruim):
                validar_chassi(ruim)
        r = self.criar_pelo_form(placa="CHA1A23", chassi="9bwzzz377vt004251")
        self.assertEqual(RegistroVip.objects.get(placa="CHA1A23").chassi, "9BWZZZ377VT004251")
        self.assertContains(self.criar_pelo_form(placa="CHB1A23", chassi="123"), "Chassi inválido")

    def test_ordem_das_datas(self):
        r = self.criar_pelo_form(data_preparacao="2026-05-10", data_vip="2026-05-09")
        self.assertContains(r, "A data VIP não pode ser anterior à data de preparação.")
        r = self.criar_pelo_form(data_preparacao="2026-05-10", data_vip="2026-05-12", data_devolucao="2026-05-11")
        self.assertContains(r, "A data de devolução não pode ser anterior à data VIP.")
        r = self.criar_pelo_form(data_preparacao="2026-05-10", data_devolucao="2026-05-09")
        self.assertContains(r, "A data de devolução não pode ser anterior à data de preparação.")
        self.assertEqual(RegistroVip.objects.count(), 0)
        ok = self.criar_pelo_form(data_preparacao="2026-05-10", data_vip="2026-05-10", data_devolucao="2026-05-10")
        self.assertEqual(ok.status_code, 302)

    def test_faixa_do_ano(self):
        self.assertContains(self.criar_pelo_form(ano="1949"), "a partir de 1950")
        self.assertContains(self.criar_pelo_form(ano=str(date.today().year + 2)), "tão no futuro")
        self.assertEqual(self.criar_pelo_form(ano=str(date.today().year + 1), placa="ANO1A23").status_code, 302)

    def test_cor_outra_exige_descricao(self):
        self.assertContains(self.criar_pelo_form(cor="outra"), "Descreva a cor.")
        self.assertEqual(self.criar_pelo_form(cor="outra", cor_outra="Verde musgo", placa="COR1A23").status_code, 302)
        self.assertEqual(RegistroVip.objects.get(placa="COR1A23").cor_texto, "Verde musgo")

    def test_campos_obrigatorios(self):
        r = self.criar_pelo_form(cliente="", servico="", placa="", data_preparacao="")
        for texto in ("Selecione o cliente.", "Informe pelo menos 1 serviço.", "Informe a placa do veículo.",
                      "Informe a data de preparação"):
            self.assertContains(r, texto)

    def test_so_cliente_placa_servico_e_data_de_preparacao_sao_obrigatorios(self):
        r = self.criar_pelo_form(marca="", modelo="", versao="", cor="", ano="", chassi="", observacao="")
        self.assertEqual(r.status_code, 302)

    def test_capacitacao_nao_aparece_entre_os_servicos(self):
        self.client.force_login(self.admin)
        resposta = self.client.get(reverse("vip_novo"))
        self.assertNotContains(resposta, "Curso")
        self.assertContains(resposta, "VIP completo")
        self.assertEqual(self.criar_pelo_form(servico=self.curso.pk).status_code, 200)   # volta com erro
        self.assertEqual(RegistroVip.objects.count(), 0)

    def test_servico_inativo_nao_e_oferecido(self):
        self.preparacao.ativo = False
        self.preparacao.save()
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("vip_novo")), "Preparação — R$")


class ValorAutomaticoTest(BaseVipTest):
    def test_valor_vem_do_servico_e_fica_guardado_no_registro(self):
        self.criar_pelo_form(placa="VAL1A23")
        r = RegistroVip.objects.get(placa="VAL1A23")
        self.assertEqual(r.valor, Decimal("150.00"))
        self.vip.valor_padrao = Decimal("999.00")        # mudar o serviço depois não altera o passado
        self.vip.save()
        r.refresh_from_db()
        self.assertEqual(r.valor, Decimal("150.00"))

    def test_administrador_pode_alterar_o_valor(self):
        self.criar_pelo_form(placa="VAL2A23", valor="175.50")
        self.assertEqual(RegistroVip.objects.get(placa="VAL2A23").valor, Decimal("175.50"))

    def test_funcionario_nao_altera_o_valor_ao_criar(self):
        self.criar_pelo_form(usuario=self.func, placa="VAL3A23", valor="1.00")
        self.assertEqual(RegistroVip.objects.get(placa="VAL3A23").valor, Decimal("150.00"))

    def test_funcionario_nao_altera_o_valor_ao_editar(self):
        r = self.registro(valor=Decimal("200.00"))
        self.client.force_login(self.func)
        dados = self.dados_form(registro=r, placa=r.placa, observacao="mudou")
        dados["itens-0-valor"] = "1.00"                       # tentativa do Funcionário
        self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        r.refresh_from_db()
        self.assertEqual((r.valor, r.itens.get().valor, r.observacao), (Decimal("200.00"), Decimal("200.00"), "mudou"))

    def test_funcionario_trocando_o_servico_recebe_o_valor_do_novo_servico(self):
        r = self.registro()
        self.client.force_login(self.func)
        dados = self.dados_form(registro=r, placa=r.placa)
        dados["itens-0-servico"] = self.preparacao.pk
        self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        r.refresh_from_db()
        item = r.itens.get()
        self.assertEqual((item.servico, item.valor, r.valor), (self.preparacao, Decimal("300.00"), Decimal("300.00")))

    def test_campo_valor_aparece_bloqueado_para_o_funcionario(self):
        self.client.force_login(self.func)
        pagina = self.client.get(reverse("vip_novo"))
        self.assertContains(pagina, 'name="itens-0-valor"')
        self.assertRegex(pagina.content.decode(), r'<input[^>]*name="itens-0-valor"[^>]*disabled')
        self.assertContains(pagina, "só o Administrador os altera")


class NotaFiscalTest(BaseVipTest):
    def test_nota_repetida_avisa_mas_nao_bloqueia(self):
        self.criar_pelo_form(placa="NFA1A23", nota_fiscal="NF-77")
        self.client.force_login(self.admin)
        r = self.client.post(reverse("vip_novo"), self.dados_form(placa="NFB1A23", nota_fiscal="nf-77"), follow=True)
        self.assertEqual(RegistroVip.objects.count(), 2)
        self.assertTrue(any("já existe em outro registro" in str(m) for m in get_messages(r.wsgi_request)))


class HistoricoTest(BaseVipTest):
    def test_criacao_e_edicoes_relevantes_sao_registradas(self):
        self.criar_pelo_form(placa="HIS1A23")
        r = RegistroVip.objects.get(placa="HIS1A23")
        dados = self.dados_form(registro=r, placa="HIS1A23", data_devolucao=self.dias(5).isoformat())
        dados["itens-0-valor"], dados["itens-0-servico"] = "200.00", self.preparacao.pk
        self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        tipos = list(r.historico.values_list("tipo", flat=True))
        self.assertEqual(tipos[0], "criacao")
        textos = " | ".join(h.valor_novo for h in r.historico.filter(tipo="itens"))
        self.assertIn("valor R$ 150,00 → R$ 200,00", textos)
        self.assertIn("serviço VIP completo → Preparação", textos)
        self.assertIn("data de devolução", " | ".join(h.valor_novo for h in r.historico.filter(tipo="edicao")))
        self.assertEqual(r.historico.first().usuario, self.admin)
