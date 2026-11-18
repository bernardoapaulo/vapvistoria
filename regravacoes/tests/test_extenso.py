from decimal import Decimal

from django.test import SimpleTestCase

from regravacoes.extenso import inteiro_por_extenso, valor_por_extenso


class ValorPorExtensoTest(SimpleTestCase):
    def test_casos_pedidos(self):
        casos = {
            "0.50": "cinquenta centavos",
            "1.00": "um real",
            "21.00": "vinte e um reais",
            "100.00": "cem reais",
            "1000.00": "mil reais",
            "1234.56": "mil, duzentos e trinta e quatro reais e cinquenta e seis centavos",
            "2000000.00": "dois milhões de reais",
        }
        for valor, esperado in casos.items():
            self.assertEqual(valor_por_extenso(Decimal(valor)), esperado, valor)

    def test_zero_centavos_e_um_centavo(self):
        self.assertEqual(valor_por_extenso(Decimal("0")), "zero real")
        self.assertEqual(valor_por_extenso(Decimal("0.01")), "um centavo")
        self.assertEqual(valor_por_extenso(Decimal("1.01")), "um real e um centavo")
        self.assertEqual(valor_por_extenso(Decimal("2.02")), "dois reais e dois centavos")

    def test_centenas_e_conectivos(self):
        casos = {"101": "cento e um reais", "110": "cento e dez reais", "999": "novecentos e noventa e nove reais",
                 "1001": "mil e um reais", "1100": "mil e cem reais", "2000": "dois mil reais",
                 "12345.67": "doze mil, trezentos e quarenta e cinco reais e sessenta e sete centavos",
                 "1500000": "um milhão e quinhentos mil reais", "1000000": "um milhão de reais",
                 "1000000000": "um bilhão de reais", "19.90": "dezenove reais e noventa centavos"}
        for valor, esperado in casos.items():
            self.assertEqual(valor_por_extenso(Decimal(valor)), esperado, valor)

    def test_arredonda_para_centavos_e_aceita_texto(self):
        self.assertEqual(valor_por_extenso("10.005"), "dez reais e um centavo")
        self.assertEqual(valor_por_extenso("5"), "cinco reais")

    def test_negativo_nao_tem_extenso(self):
        with self.assertRaises(ValueError):
            valor_por_extenso(Decimal("-1"))

    def test_inteiro_por_extenso(self):
        self.assertEqual(inteiro_por_extenso(0), "zero")
        self.assertEqual(inteiro_por_extenso(16), "dezesseis")
        self.assertEqual(inteiro_por_extenso(1_000_001), "um milhão e um")
