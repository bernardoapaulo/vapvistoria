from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from atendimentos.models import Atendimento
from cadastros.models import Aluno, Cliente, Veiculo
from contas.permissoes import ADMINISTRADOR, FUNCIONARIO
from servicos.models import TipoServico

Cat = TipoServico.Categoria


class BaseAtendimentoTest(TestCase):
    """Cria usuários dos dois perfis e dados mínimos para os testes de atendimento."""

    @classmethod
    def setUpTestData(cls):
        Usuario = get_user_model()
        cls.admin = Usuario.objects.create_user("adm", password="x")
        cls.admin.groups.add(Group.objects.get(name=ADMINISTRADOR))
        cls.func = Usuario.objects.create_user("func", password="x")
        cls.func.groups.add(Group.objects.get(name=FUNCIONARIO))

        cls.cliente = Cliente.objects.create(nome="Maria Teste", telefone="1")
        cls.outro_cliente = Cliente.objects.create(nome="João Teste", telefone="2")
        cls.veiculo = Veiculo.objects.create(
            placa="ABC1234", marca="Fiat", modelo="Uno", ano=2012, cor="Branco", proprietario=cls.cliente)
        cls.veiculo_outro = Veiculo.objects.create(
            placa="XYZ9876", marca="Ford", modelo="Ka", ano=2015, cor="Azul", proprietario=cls.outro_cliente)
        cls.aluno = Aluno.objects.create(nome="Aluno Teste", celular="3")

        cls.vistoria = TipoServico.objects.create(nome="Vistoria", categoria=Cat.VISTORIA, valor_padrao="250.00")
        cls.limpeza = TipoServico.objects.create(nome="Limpeza", categoria=Cat.LIMPEZA, valor_padrao="100.00")
        cls.curso = TipoServico.objects.create(nome="Curso", categoria=Cat.CAPACITACAO, valor_padrao="900.00")

    def receber(self, atendimento, valor=None, forma="pix", data=None, usuario=None):
        """Registra um recebimento pela regra de negócio (padrão: o saldo todo, hoje)."""
        from django.utils import timezone

        from financeiro import regras
        valor = atendimento.valor_final - atendimento.valor_pago if valor is None else Decimal(valor)
        return regras.registrar_recebimento(
            atendimento, valor, data or timezone.localdate(), forma, "", usuario or self.admin)

    def criar(self, **extra):
        """Cria um atendimento válido direto no banco (sem passar pelo formulário)."""
        dados = dict(cliente=self.cliente, tipo_servico=self.vistoria, veiculo=self.veiculo,
                     valor_cobrado=Decimal("250.00"), registrado_por=self.admin)
        dados.update(extra)
        return Atendimento.objects.create(**dados)

    def dados_form(self, **extra):
        """Dados POST de um atendimento de vistoria válido."""
        dados = {
            "cliente": self.cliente.pk, "tipo_servico": self.vistoria.pk, "veiculo": self.veiculo.pk,
            "data_atendimento": date.today().isoformat(), "status": "solicitado",
            "valor_cobrado": "250.00", "desconto": "0", "observacoes": "",
        }
        dados.update(extra)
        return {k: v for k, v in dados.items() if v is not None}
