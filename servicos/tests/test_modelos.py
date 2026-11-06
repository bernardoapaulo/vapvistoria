from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from servicos.models import TipoServico


class TipoServicoTest(TestCase):
    def test_criacao_e_str(self):
        s = TipoServico.objects.create(
            nome="Limpeza completa", categoria=TipoServico.Categoria.LIMPEZA, valor_padrao=Decimal("120.00"),
        )
        self.assertTrue(s.ativo)
        self.assertEqual(str(s), "Limpeza completa")
        self.assertEqual(s.get_categoria_display(), "Limpeza")

    def test_valor_negativo_e_invalido(self):
        s = TipoServico(nome="X", categoria=TipoServico.Categoria.LIMPEZA, valor_padrao=Decimal("-1"))
        with self.assertRaises(ValidationError):
            s.full_clean()
