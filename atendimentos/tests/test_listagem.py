from datetime import date, timedelta

from django.urls import reverse

from .base import BaseAtendimentoTest


class ListagemAtendimentoTest(BaseAtendimentoTest):
    def setUp(self):
        hoje = date.today()
        self.a1 = self.criar(status="solicitado", data_atendimento=hoje)
        self.a2 = self.criar(status="concluido", tipo_servico=self.limpeza, data_atendimento=hoje - timedelta(days=40))
        self.receber(self.a2)
        self.a3 = self.criar(status="cancelado", cliente=self.outro_cliente, veiculo=self.veiculo_outro,
                             data_atendimento=hoje - timedelta(days=10))
        self.a4 = self.criar(status="em_andamento", tipo_servico=self.curso, veiculo=None, aluno=self.aluno,
                             data_atendimento=hoje - timedelta(days=3))
        self.receber(self.a4, "100.00", "dinheiro")
        self.client.force_login(self.func)

    def _ids(self, **filtros):
        resp = self.client.get(reverse("atendimento_lista"), filtros)
        self.assertEqual(resp.status_code, 200)
        return {a.pk for a in resp.context["object_list"]}

    def test_sem_filtro_lista_tudo(self):
        self.assertEqual(self._ids(), {self.a1.pk, self.a2.pk, self.a3.pk, self.a4.pk})

    def test_filtro_por_status(self):
        self.assertEqual(self._ids(status="concluido"), {self.a2.pk})

    def test_filtro_por_categoria(self):
        self.assertEqual(self._ids(categoria="limpeza"), {self.a2.pk})
        self.assertEqual(self._ids(categoria="capacitacao"), {self.a4.pk})

    def test_filtro_por_pagamento(self):
        self.assertEqual(self._ids(pagamento="pago"), {self.a2.pk})
        self.assertEqual(self._ids(pagamento="parcial"), {self.a4.pk})

    def test_filtro_por_cliente(self):
        self.assertEqual(self._ids(cliente=self.outro_cliente.pk), {self.a3.pk})

    def test_filtro_por_periodo(self):
        de = (date.today() - timedelta(days=15)).isoformat()
        self.assertEqual(self._ids(de=de), {self.a1.pk, self.a3.pk, self.a4.pk})
        ate = (date.today() - timedelta(days=15)).isoformat()
        self.assertEqual(self._ids(ate=ate), {self.a2.pk})
        self.assertEqual(self._ids(de=(date.today() - timedelta(days=5)).isoformat(),
                                   ate=(date.today() - timedelta(days=1)).isoformat()), {self.a4.pk})

    def test_busca_por_placa_cliente_e_aluno(self):
        self.assertEqual(self._ids(q="XYZ9876"), {self.a3.pk})
        self.assertEqual(self._ids(q="João"), {self.a3.pk})
        self.assertEqual(self._ids(q="Aluno Teste"), {self.a4.pk})

    def test_filtros_combinados_e_valores_invalidos_sao_ignorados(self):
        self.assertEqual(self._ids(status="concluido", categoria="vistoria_cautelar"), set())
        self.assertEqual(len(self._ids(status="xxx", de="lixo", cliente="abc")), 4)

    def test_ordenacao_mais_recente_primeiro(self):
        resp = self.client.get(reverse("atendimento_lista"))
        datas = [a.data_atendimento for a in resp.context["object_list"]]
        self.assertEqual(datas, sorted(datas, reverse=True))

    def test_paginacao_preserva_filtros(self):
        for _ in range(16):
            self.criar(status="agendado")
        resp = self.client.get(reverse("atendimento_lista"), {"status": "agendado"})
        self.assertEqual(len(resp.context["object_list"]), 15)
        self.assertContains(resp, "status=agendado&page=2")

    def test_listagem_usa_poucas_consultas(self):
        for _ in range(10):
            self.criar()
        with self.assertNumQueries(7):
            self.client.get(reverse("atendimento_lista"))

    def test_historico_na_tela_do_cliente_veiculo_e_aluno(self):
        resp = self.client.get(reverse("cliente_detalhe", args=[self.cliente.pk]))
        self.assertContains(resp, "Total gasto")
        self.assertEqual(resp.context["totais"]["total"], 750)  # a1 + a2 + a4? (a3 é de outro cliente)
        self.assertContains(self.client.get(reverse("veiculo_detalhe", args=[self.veiculo.pk])), "Histórico do veículo")
        resp = self.client.get(reverse("aluno_detalhe", args=[self.aluno.pk]))
        self.assertContains(resp, "Cursos e serviços")
        self.assertEqual(len(resp.context["atendimentos"]), 1)

    def test_inicio_mostra_em_aberto_e_recentes(self):
        resp = self.client.get(reverse("inicio"))
        self.assertEqual(resp.context["total_em_aberto"], 2)  # solicitado + em andamento
        self.assertContains(resp, "Atendimentos recentes")
