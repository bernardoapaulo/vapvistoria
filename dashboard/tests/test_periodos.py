from datetime import date

from django.test import SimpleTestCase

from dashboard import periodos
from dashboard.services import variacao, variacao_pontos


class PeriodosTest(SimpleTestCase):
    HOJE = date(2026, 10, 30)

    def _calc(self, chave, **kw):
        return periodos.calcular(chave, hoje=self.HOJE, **kw)

    def test_este_mes_e_comparativo_com_o_mesmo_trecho_do_mes_anterior(self):
        p = self._calc(periodos.ESTE_MES)
        self.assertEqual((p.inicio, p.fim), (date(2026, 10, 1), date(2026, 10, 30)))
        self.assertEqual((p.anterior.inicio, p.anterior.fim), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(p.rotulo_comparativo, "vs. mês passado")

    def test_anterior_nao_passa_do_fim_do_mes_anterior(self):
        p = periodos.calcular(periodos.ESTE_MES, hoje=date(2026, 3, 31))
        self.assertEqual((p.anterior.inicio, p.anterior.fim), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_mes_passado(self):
        p = self._calc(periodos.MES_PASSADO)
        self.assertEqual((p.inicio, p.fim), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual((p.anterior.inicio, p.anterior.fim), (date(2026, 8, 1), date(2026, 8, 31)))

    def test_ultimos_3_e_6_meses_sao_meses_de_calendario_ate_hoje(self):
        self.assertEqual(self._calc(periodos.ULTIMOS_3_MESES).inicio, date(2026, 8, 1))
        self.assertEqual(self._calc(periodos.ULTIMOS_6_MESES).inicio, date(2026, 5, 1))
        p = self._calc(periodos.ULTIMOS_3_MESES)
        self.assertEqual(p.fim, self.HOJE)
        self.assertEqual(p.anterior.fim, date(2026, 7, 31))
        self.assertEqual(p.anterior.dias, p.dias)

    def test_virada_de_ano(self):
        p = periodos.calcular(periodos.ULTIMOS_3_MESES, hoje=date(2026, 1, 15))
        self.assertEqual(p.inicio, date(2025, 11, 1))
        self.assertEqual(periodos.primeiro_dia_meses_atras(date(2026, 1, 15), 1), date(2025, 12, 1))

    def test_este_ano(self):
        p = self._calc(periodos.ESTE_ANO)
        self.assertEqual((p.inicio, p.fim), (date(2026, 1, 1), self.HOJE))
        self.assertEqual((p.anterior.inicio, p.anterior.fim), (date(2025, 1, 1), date(2025, 10, 30)))

    def test_personalizado_inverte_datas_trocadas(self):
        p = self._calc(periodos.PERSONALIZADO, de=date(2026, 5, 10), ate=date(2026, 5, 1))
        self.assertEqual((p.inicio, p.fim), (date(2026, 5, 1), date(2026, 5, 10)))
        self.assertEqual((p.anterior.inicio, p.anterior.fim), (date(2026, 4, 21), date(2026, 4, 30)))

    def test_chave_invalida_ou_personalizado_sem_datas_vira_este_mes(self):
        self.assertEqual(self._calc("lixo").chave, periodos.ESTE_MES)
        self.assertEqual(self._calc(periodos.PERSONALIZADO).chave, periodos.ESTE_MES)


class VariacaoTest(SimpleTestCase):
    def test_variacao_percentual(self):
        self.assertEqual(variacao(120, 100), {"texto": "+20%", "sentido": "positivo"})
        self.assertEqual(variacao(80, 100), {"texto": "-20%", "sentido": "negativo"})

    def test_menor_e_melhor_inverte_a_cor(self):
        self.assertEqual(variacao(80, 100, menor_e_melhor=True)["sentido"], "positivo")

    def test_sem_base_de_comparacao(self):
        self.assertEqual(variacao(5, 0)["texto"], "novo (antes: 0)")
        self.assertEqual(variacao(0, 0)["texto"], "sem variação")
        self.assertEqual(variacao(None, 3)["sentido"], "neutro")

    def test_variacao_em_pontos_percentuais(self):
        self.assertEqual(variacao_pontos(66.7, 60.0), {"texto": "+6,7 p.p.", "sentido": "positivo"})
        self.assertEqual(variacao_pontos(10.0, 12.5, menor_e_melhor=True), {"texto": "-2,5 p.p.", "sentido": "positivo"})
        self.assertEqual(variacao_pontos(None, 12.5)["sentido"], "neutro")
