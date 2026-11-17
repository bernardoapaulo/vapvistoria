from decimal import Decimal

from django.urls import reverse

from atendimentos.models import Atendimento
from financeiro import regras as financeiro
from financeiro.models import Recebimento
from vip_preparacao import regras
from vip_preparacao.models import ItemServicoVip, RegistroVip

from .base import BaseVipTest

D = Decimal


class ItensDeServicoTest(BaseVipTest):
    def test_total_e_a_soma_dos_itens(self):
        r = self.registro(itens=[(self.vip, "150.00"), (self.polimento, "80.00"), (self.preparacao, "300.00")])
        self.assertEqual(r.valor, D("530.00"))
        self.assertEqual(r.total_itens, D("530.00"))

    def test_cria_com_varios_servicos_e_cada_item_usa_o_valor_padrao_do_servico(self):
        self.criar_pelo_form(placa="MUL1A23", itens=[(self.vip, "", ""), (self.polimento, "", "só o capô"), (self.preparacao, "", "")])
        r = RegistroVip.objects.get(placa="MUL1A23")
        self.assertEqual([(i.servico, i.valor, i.observacao) for i in r.itens.order_by("id")],
                         [(self.vip, D("150.00"), ""), (self.polimento, D("80.00"), "só o capô"), (self.preparacao, D("300.00"), "")])
        self.assertEqual(r.valor, D("530.00"))
        self.assertIn("VIP completo, Polimento, Preparação", r.historico.get(tipo="criacao").valor_novo)

    def test_valor_do_item_fica_guardado_no_item(self):
        r = self.registro(itens=[(self.vip, "150.00")])
        self.vip.valor_padrao = D("999.00")
        self.vip.save()
        self.assertEqual(r.itens.get().valor, D("150.00"))
        self.assertEqual(RegistroVip.objects.get().valor, D("150.00"))

    def test_obrigatorio_pelo_menos_um_servico(self):
        for servico in ("", None):
            r = self.criar_pelo_form(servico=servico, itens=[] if servico is None else None)
            self.assertContains(r, "Informe pelo menos 1 serviço.")
        self.assertEqual(RegistroVip.objects.count(), 0)

    def test_nao_deixa_remover_o_ultimo_servico(self):
        r = self.registro()
        dados = self.dados_form(registro=r, placa=r.placa)
        dados["itens-0-DELETE"] = "on"
        self.client.force_login(self.admin)
        resposta = self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        self.assertContains(resposta, "Informe pelo menos 1 serviço.")
        self.assertEqual(r.itens.count(), 1)

    def test_mesmo_servico_pode_repetir_e_cada_linha_e_um_item(self):
        self.criar_pelo_form(placa="REP1A23", itens=[(self.vip, "", "frente"), (self.vip, "", "traseira")])
        r = RegistroVip.objects.get(placa="REP1A23")
        self.assertEqual(r.itens.count(), 2)
        self.assertEqual(r.valor, D("300.00"))

    def test_funcionario_nao_altera_valor_do_item_ao_criar(self):
        self.criar_pelo_form(usuario=self.func, placa="FUN2A23", itens=[(self.vip, "1.00", ""), (self.polimento, "2.00", "")])
        r = RegistroVip.objects.get(placa="FUN2A23")
        self.assertEqual(sorted(i.valor for i in r.itens.all()), [D("80.00"), D("150.00")])
        self.assertEqual(r.valor, D("230.00"))

    def test_funcionario_nao_altera_valor_ao_editar_mas_novo_item_vem_com_valor_padrao(self):
        r = self.registro(itens=[(self.vip, "200.00")])               # valor combinado diferente do padrão
        dados = self.dados_form(registro=r, placa=r.placa, itens=[(self.polimento, "1.00", "")])
        dados["itens-0-valor"] = "5.00"
        self.client.force_login(self.func)
        self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        self.assertEqual(sorted(r.itens.values_list("valor", flat=True)), [D("80.00"), D("200.00")])
        r.refresh_from_db()
        self.assertEqual(r.valor, D("280.00"))

    def test_administrador_altera_valor_do_item(self):
        r = self.registro(itens=[(self.vip, "150.00")])
        dados = self.dados_form(registro=r, placa=r.placa)
        dados["itens-0-valor"] = "175.50"
        self.client.force_login(self.admin)
        self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        r.refresh_from_db()
        self.assertEqual((r.itens.get().valor, r.valor), (D("175.50"), D("175.50")))

    def test_editar_adiciona_remove_e_altera_itens_e_registra_no_historico(self):
        r = self.registro(itens=[(self.vip, "150.00"), (self.polimento, "80.00")])
        a, b = r.itens.order_by("id")
        dados = self.dados_form(registro=r, placa=r.placa, itens=[(self.preparacao, "300.00", "novo")])
        dados["itens-0-valor"] = "160.00"          # altera o 1º
        dados["itens-1-DELETE"] = "on"             # remove o 2º
        self.client.force_login(self.admin)
        self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        r.refresh_from_db()
        self.assertEqual(sorted((i.servico.nome, i.valor) for i in r.itens.all()), [("Preparação", D("300.00")), ("VIP completo", D("160.00"))])
        self.assertEqual(r.valor, D("460.00"))
        textos = " | ".join(h.valor_novo for h in r.historico.filter(tipo="itens"))
        self.assertIn("valor R$ 150,00 → R$ 160,00", textos)
        self.assertIn("item removido", textos)
        self.assertIn("item adicionado: Preparação (R$ 300,00)", textos)

    def test_servico_inativo_continua_no_item_antigo_mas_nao_e_oferecido(self):
        r = self.registro(itens=[(self.polimento, "80.00")])
        self.polimento.ativo = False
        self.polimento.save()
        self.client.force_login(self.admin)
        pagina = self.client.get(reverse("vip_editar", args=[r.pk]))
        self.assertContains(pagina, "Polimento — R$")                # o item que já existe segue visível
        self.assertNotContains(pagina, 'data-nome="Polimento"')    # mas não aparece mais no pop-up para novos itens


class ListaEDetalheComVariosServicosTest(BaseVipTest):
    def setUp(self):
        super().setUp()
        self.r = self.registro(itens=[(self.vip, "150.00"), (self.polimento, "80.00"), (self.preparacao, "300.00")], placa="LST1A23")
        self.u = self.registro(itens=[(self.vip, "150.00")], placa="LST2A23")
        self.client.force_login(self.admin)

    def test_lista_mostra_primeiro_servico_mais_n_e_o_total(self):
        html = self.client.get(reverse("vip_lista")).content.decode()
        self.assertIn("VIP completo +2", html)
        self.assertIn('title="VIP completo + Polimento + Preparação"', html)
        self.assertIn("R$ 530,00", html)

    def test_detalhe_mostra_todos_os_itens_com_valores_e_total(self):
        html = self.client.get(self.r.get_absolute_url()).content.decode()
        for esperado in ("VIP completo", "Polimento", "Preparação", "R$ 150,00", "R$ 80,00", "R$ 300,00", "R$ 530,00"):
            self.assertIn(esperado, html)

    def test_busca_considera_todos_os_itens(self):
        resposta = self.client.get(reverse("vip_lista"), {"q": "polimento"})
        self.assertEqual([x.placa for x in resposta.context["object_list"]], ["LST1A23"])

    def test_filtro_por_servico_considera_todos_os_itens_sem_repetir_linhas(self):
        resposta = self.client.get(reverse("vip_lista"), {"servico": self.vip.pk})
        self.assertEqual(sorted(x.placa for x in resposta.context["object_list"]), ["LST1A23", "LST2A23"])
        resposta = self.client.get(reverse("vip_lista"), {"servico": self.preparacao.pk})
        self.assertEqual([x.placa for x in resposta.context["object_list"]], ["LST1A23"])
        # o mesmo serviço duas vezes no mesmo registro não duplica a linha
        ItemServicoVip.objects.create(registro=self.r, servico=self.vip, valor=D("150.00"))
        resposta = self.client.get(reverse("vip_lista"), {"servico": self.vip.pk})
        self.assertEqual(sorted(x.placa for x in resposta.context["object_list"]), ["LST1A23", "LST2A23"])

    def test_ordenar_por_valor_usa_o_total(self):
        resposta = self.client.get(reverse("vip_lista"), {"ordem": "-valor"})
        self.assertEqual([x.placa for x in resposta.context["object_list"]], ["LST1A23", "LST2A23"])

    def test_lista_nao_faz_consulta_por_linha_com_varios_itens(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for i in range(10):
            self.registro(itens=[(self.vip, "1"), (self.polimento, "2")], placa=f"QRY{i % 10}A{i:02d}")
        with CaptureQueriesContext(connection) as q:
            self.client.get(reverse("vip_lista"))
        self.assertLess(len(q), 16, [x["sql"][:80] for x in q])


class RateioTest(BaseVipTest):
    """A soma dos recebimentos tem de ser EXATAMENTE o total, mesmo quando os centavos não dividem."""

    def test_ratear_em_partes_iguais_o_ultimo_absorve_a_diferenca(self):
        partes = regras.ratear(D("100.00"), [D("1"), D("1"), D("1")])
        self.assertEqual(partes, [D("33.33"), D("33.33"), D("33.34")])
        self.assertEqual(sum(partes), D("100.00"))

    def test_ratear_proporcional_aos_valores(self):
        partes = regras.ratear(D("530.00"), [D("150.00"), D("80.00"), D("300.00")])
        self.assertEqual(partes, [D("150.00"), D("80.00"), D("300.00")])
        partes = regras.ratear(D("100.01"), [D("150.00"), D("80.00"), D("300.00")])
        self.assertEqual(sum(partes), D("100.01"))
        self.assertTrue(all(p > 0 for p in partes))

    def test_soma_sempre_fecha_em_muitos_casos(self):
        import random
        rnd = random.Random(7)
        for _ in range(300):
            valores = [D(rnd.randint(1, 99999)) / 100 for _ in range(rnd.randint(1, 6))]
            total = D(rnd.randint(1, 500000)) / 100
            partes = regras.ratear(total, valores)
            self.assertEqual(sum(partes), total.quantize(D("0.01")), (total, valores))
            self.assertEqual(len(partes), len(valores))

    def test_ratear_sem_valores_levanta_erro(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            regras.ratear(D("10.00"), [D("0"), D("0")])


class ConclusaoComVariosServicosTest(BaseVipTest):
    def setUp(self):
        super().setUp()
        self.r = self.registro(
            itens=[(self.vip, "150.00"), (self.polimento, "80.00"), (self.preparacao, "300.00")], data_devolucao=self.dias(-1))

    def concluida(self, **extra):
        self.concluir(self.r, **extra)
        self.r.refresh_from_db()
        return self.r

    def test_cria_um_atendimento_e_um_recebimento_por_item_e_a_soma_fecha(self):
        r = self.concluida(forma="cartao_credito")
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (3, 3))
        por_item = {i.servico.nome: i for i in r.itens.select_related("atendimento", "servico")}
        for nome, valor in (("VIP completo", "150.00"), ("Polimento", "80.00"), ("Preparação", "300.00")):
            a = por_item[nome].atendimento
            self.assertEqual((a.tipo_servico.nome, a.valor_cobrado, a.status, a.situacao_pagamento), (nome, D(valor), "concluido", "pago"))
            self.assertEqual(a.cliente, self.cliente)
            self.assertEqual(a.data_atendimento, self.dias(-1))
            (rec,) = a.recebimentos.validos()
            self.assertEqual((rec.valor, rec.forma), (D(valor), "cartao_credito"))
        self.assertEqual(sum(x.valor for a in r.atendimentos for x in a.recebimentos.validos()), r.valor)
        self.assertEqual(r.valor, D("530.00"))
        self.assertEqual(r.status, "concluido")

    def test_vinculo_de_volta_ao_registro(self):
        r = self.concluida()
        for item in r.itens.all():
            self.assertEqual(item.atendimento.item_vip.registro, r)
        self.assertEqual(r.atendimentos.count(), 3)
        self.assertEqual({rec.observacao for a in r.atendimentos for rec in a.recebimentos.all()},
                         {f"VIP/Preparação #{r.pk} · VIP completo", f"VIP/Preparação #{r.pk} · Polimento", f"VIP/Preparação #{r.pk} · Preparação"})

    def test_dashboard_por_servico_e_categoria_fica_certo(self):
        self.concluida()
        por_categoria = {}
        for a in Atendimento.objects.filter(item_vip__registro=self.r).select_related("tipo_servico"):
            por_categoria[a.tipo_servico.categoria] = por_categoria.get(a.tipo_servico.categoria, 0) + a.valor_cobrado
        self.assertEqual(por_categoria, {"limpeza": D("230.00"), "pequenos_reparos": D("300.00")})

    def test_concluir_duas_vezes_nao_duplica_nada(self):
        self.concluir(self.r)
        segunda = self.concluir(self.r)
        self.assertContains(segunda, "já foi concluído")
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (3, 3))

    def test_total_alterado_pelo_administrador_reajusta_os_itens_e_fecha_a_soma(self):
        r = self.concluida(valor="100.01")
        self.assertEqual(r.valor, D("100.01"))
        valores = [i.valor for i in r.itens.order_by("id")]
        self.assertEqual(sum(valores), D("100.01"))
        self.assertEqual(sum(x.valor for a in r.atendimentos for x in a.recebimentos.validos()), D("100.01"))
        self.assertEqual([a.valor_cobrado for a in r.atendimentos.order_by("id")], valores)
        textos = " | ".join(h.valor_novo for h in r.historico.filter(tipo="itens"))
        self.assertIn("total alterado na conclusão", textos)
        self.assertIn("total alterado de R$ 530,00", r.historico.get(tipo="conclusao").valor_novo)

    def test_total_em_centavos_que_nao_dividem_exatamente(self):
        r = self.registro(itens=[(self.vip, "10.00"), (self.polimento, "10.00"), (self.preparacao, "10.00")], placa="CEN1A23")
        self.concluir(r, valor="100.00")
        r.refresh_from_db()
        self.assertEqual(sorted(i.valor for i in r.itens.all()), [D("33.33"), D("33.33"), D("33.34")])
        self.assertEqual(sum(x.valor for a in r.atendimentos for x in a.recebimentos.validos()), D("100.00"))

    def test_funcionario_nao_altera_o_total(self):
        r = self.concluida(usuario=self.func, valor="1.00")
        self.assertEqual(r.valor, D("530.00"))
        self.assertEqual(sum(x.valor for a in r.atendimentos for x in a.recebimentos.validos()), D("530.00"))

    def test_item_sem_valor_impede_a_conclusao(self):
        item = self.r.itens.first()
        item.valor = D("0.00")
        item.save()
        resposta = self.concluir(self.r)
        self.assertContains(resposta, "valor maior que zero")
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (0, 0))

    def test_registro_sem_itens_nao_conclui(self):
        self.r.itens.all().delete()
        self.assertContains(self.concluir(self.r), "não tem serviços")

    def test_mes_fechado_bloqueia_e_nada_e_gravado(self):
        from datetime import timedelta
        hoje = self.dias(0)
        mes = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
        financeiro.fechar_mes(mes, self.admin)
        resposta = self.concluir(self.r, data=mes.replace(day=10).isoformat())
        self.assertContains(resposta, "está fechado")
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (0, 0))
        self.assertTrue(all(i.atendimento_id is None for i in self.r.itens.all()))

    def test_falha_no_meio_nao_deixa_lancamentos_pela_metade(self):
        # o 3º item recusaria o recebimento: tudo volta atrás (transação atômica)
        from unittest import mock
        original = financeiro.registrar_recebimento
        chamadas = []

        def falha_no_terceiro(*a, **k):
            chamadas.append(1)
            if len(chamadas) == 3:
                from django.core.exceptions import ValidationError
                raise ValidationError("falha simulada")
            return original(*a, **k)

        with mock.patch("vip_preparacao.regras.financeiro.registrar_recebimento", side_effect=falha_no_terceiro):
            resposta = self.concluir(self.r)
        self.assertContains(resposta, "falha simulada")
        self.assertEqual((Atendimento.objects.count(), Recebimento.objects.count()), (0, 0))
        self.assertEqual(RegistroVip.objects.get().status, "em_andamento")


class ReaberturaComVariosServicosTest(BaseVipTest):
    def setUp(self):
        super().setUp()
        self.r = self.registro(itens=[(self.vip, "150.00"), (self.polimento, "80.00")])
        self.concluir(self.r)
        self.r.refresh_from_db()
        self.client.force_login(self.admin)

    def reabrir(self):
        return self.client.post(reverse("vip_reabrir", args=[self.r.pk]), follow=True)

    def test_estorna_todos_os_recebimentos_e_reabre_todos_os_atendimentos(self):
        self.assertContains(self.reabrir(), "Registro reaberto")
        self.r.refresh_from_db()
        self.assertEqual(self.r.status, "em_andamento")
        self.assertEqual((Recebimento.objects.count(), Recebimento.objects.validos().count()), (2, 0))   # nada apagado
        for a in self.r.atendimentos:
            self.assertEqual((a.status, a.situacao_pagamento, a.valor_pago), ("em_andamento", "pendente", D("0.00")))
            self.assertTrue(a.historico.filter(tipo="reabertura").exists())
        self.assertEqual(self.r.historico.filter(tipo="reabertura").count(), 1)

    def test_concluir_de_novo_reaproveita_os_atendimentos(self):
        self.reabrir()
        self.concluir(self.r)
        self.assertEqual(Atendimento.objects.count(), 2)
        self.assertEqual((Recebimento.objects.count(), Recebimento.objects.validos().count()), (4, 2))

    def test_remover_item_de_registro_reaberto_cancela_o_atendimento_dele(self):
        self.reabrir()
        r = RegistroVip.objects.get(pk=self.r.pk)
        removido = r.itens.get(servico=self.polimento)
        atendimento = removido.atendimento
        dados = self.dados_form(registro=r, placa=r.placa)
        n = [i for i, x in enumerate(r.itens.order_by("id")) if x.pk == removido.pk][0]
        dados[f"itens-{n}-DELETE"] = "on"
        self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        atendimento.refresh_from_db()
        self.assertEqual(atendimento.status, "cancelado")                       # cancelado, nunca apagado
        self.assertIn("Item removido do registro", atendimento.observacoes)
        self.assertFalse(r.itens.filter(servico=self.polimento).exists())
        self.concluir(r)
        self.assertEqual(Recebimento.objects.validos().count(), 1)               # só o item que ficou foi recebido de novo

    def test_item_novo_em_registro_reaberto_ganha_atendimento_ao_concluir(self):
        self.reabrir()
        r = RegistroVip.objects.get(pk=self.r.pk)
        dados = self.dados_form(registro=r, placa=r.placa, itens=[(self.preparacao, "", "")])
        self.client.post(reverse("vip_editar", args=[r.pk]), dados)
        self.concluir(r)
        self.assertEqual(Atendimento.objects.exclude(status="cancelado").count(), 3)
        self.assertEqual(Recebimento.objects.validos().count(), 3)

    def test_mes_fechado_bloqueia_a_reabertura_com_varios_itens(self):
        from datetime import timedelta
        mes = (self.dias(0).replace(day=1) - timedelta(days=1)).replace(day=1)
        novo = self.registro(itens=[(self.vip, "10.00"), (self.polimento, "20.00")], placa="MES1A23")
        regras.concluir(novo, None, "pix", mes.replace(day=10), self.admin, False)
        financeiro.fechar_mes(mes, self.admin)
        resposta = self.client.post(reverse("vip_reabrir", args=[novo.pk]), follow=True)
        self.assertContains(resposta, "está fechado")
        novo.refresh_from_db()
        self.assertEqual(novo.status, "concluido")
        self.assertEqual(Recebimento.objects.filter(atendimento__item_vip__registro=novo).validos().count(), 2)

    def test_concluido_nao_aceita_mudar_itens(self):
        self.client.post(reverse("vip_reabrir", args=[self.r.pk]))   # reabre...
        self.concluir(self.r)                                        # ...e conclui de novo
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            regras.salvar_itens(self.r, [], self.admin)
