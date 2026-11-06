"""
Despesas FICTÍCIAS de 12 meses (fixas e variáveis, algumas recorrentes, algumas em aberto e
vencidas, outras a vencer) e meses fechados, para testar o Financeiro. Os recebimentos fictícios
nascem junto com os atendimentos (atendimentos/dados_ficticios.py). Nunca usa dados reais.
Usado pelo comando `popular_dados`.
"""
import calendar
import random
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from dashboard.services import ultimos_meses
from servicos.models import TipoServico

from . import regras
from .migracao_pagamentos import CATEGORIAS_PADRAO
from .models import CategoriaDespesa, Despesa, FechamentoMes, FormaPagamento, RegistroAuditoria

Entidade = RegistroAuditoria.Entidade
FORMAS_DESPESA = [FormaPagamento.PIX, FormaPagamento.TRANSFERENCIA, FormaPagamento.DEBITO, FormaPagamento.DINHEIRO]

# (descrição, categoria, valor base, dia do vencimento, fornecedor, serviço direto, variação em %)
FIXAS = [
    ("Aluguel do galpão", "Aluguel", 1100, 5, "Imobiliária Exemplo", None, 0),
    ("Luz, água e internet", "Água/Luz/Internet", 320, 10, "Concessionárias Fictícias", None, 12),
    ("Folha de pagamento", "Salários e encargos", 1500, 5, "", None, 0),
    ("Anúncios online", "Marketing", 200, 15, "Agência Modelo", None, 10),
]
VARIAVEIS = [
    ("Produtos de limpeza", "Material de limpeza", 170, 12, "Distribuidora Imaginária", "Limpeza completa", 45, 0.9),
    ("Peças para reparos", "Peças e reparos", 150, 18, "Auto Peças Modelo", "Reparo de farol", 50, 0.7),
    ("Taxa do órgão de vistoria", "Impostos e taxas", 150, 14, "Órgão Fictício", "Vistoria cautelar - carro", 35, 0.9),
    ("Instrutor do curso", "Instrutores/cursos", 420, 25, "Instrutor Exemplo", "Curso de capacitação veicular", 20, 0.8),
    ("Impostos do mês", "Impostos e taxas", 300, 20, "Receita Fictícia", None, 30, 1.0),
    ("Combustível", "Combustível", 190, 8, "Posto Exemplo", None, 35, 1.0),
    ("Manutenção das instalações", "Manutenção", 200, 22, "Manutenções Modelo", None, 70, 0.5),
]
PONTUAIS = [  # (meses atrás, descrição, categoria, valor, dia)
    (9, "Compra de aspirador industrial", "Equipamentos", 900, 17),
    (5, "Ferramentas de regravação", "Equipamentos", 1300, 9),
    (2, "Compressor de ar", "Equipamentos", 700, 11),
]


def _dia(mes, dia):
    return date(mes.year, mes.month, min(dia, calendar.monthrange(mes.year, mes.month)[1]))


def gerar_despesas(usuarios, refazer=False):
    """Retorna quantas despesas foram criadas (0 se já existiam e refazer=False)."""
    if Despesa.objects.exists():
        if not refazer:
            return 0
        Despesa.objects.all().delete()
        FechamentoMes.objects.all().delete()
        RegistroAuditoria.objects.filter(entidade__in=[Entidade.DESPESA, Entidade.MES]).delete()

    rnd = random.Random(2027)
    hoje = timezone.localdate()
    admin = usuarios[0]
    for nome in CATEGORIAS_PADRAO:
        CategoriaDespesa.objects.get_or_create(nome=nome)
    categorias = {c.nome: c for c in CategoriaDespesa.objects.all()}
    servicos = {t.nome: t for t in TipoServico.objects.all()}
    meses = ultimos_meses(12)
    criadas = []

    def lancar(mes_atras, descricao, categoria, valor, dia, mes, fornecedor="", servico=None, origem=None,
               recorrente=False, aberta=False):
        vencimento = _dia(mes, dia)
        pago = vencimento <= hoje and not aberta
        data_pagamento = min(vencimento + timedelta(days=rnd.randint(-2, 2)), hoje) if pago else None
        d = Despesa.objects.create(
            descricao=descricao, categoria=categorias[categoria], valor=Decimal(valor).quantize(Decimal("0.01")),
            vencimento=vencimento, data_pagamento=data_pagamento,
            forma_pagamento=rnd.choice(FORMAS_DESPESA) if pago else "", fornecedor=fornecedor,
            tipo_servico=servicos.get(servico) if servico else None, recorrente=recorrente, origem=origem,
            criado_por=admin, alterado_por=admin)
        criadas.append(d)
        return d

    modelos = {}
    for i, mes in enumerate(meses):
        atras = len(meses) - 1 - i
        for descricao, categoria, valor, dia, fornecedor, _, variacao in FIXAS:
            v = valor * (1 + rnd.uniform(-variacao, variacao) / 100)
            if i == 0:  # a primeira da série é o "modelo" que a recorrência copia nos meses seguintes
                modelos[descricao] = lancar(atras, descricao, categoria, v, dia, mes, fornecedor, recorrente=True)
            else:
                lancar(atras, descricao, categoria, v, dia, mes, fornecedor, origem=modelos[descricao])
        for descricao, categoria, valor, dia, fornecedor, servico, variacao, chance in VARIAVEIS:
            if rnd.random() > chance:
                continue
            v = valor * (1 + rnd.uniform(-variacao, variacao) / 100)
            # algumas em aberto e vencidas (em meses que continuam abertos para edição)
            aberta = (atras == 2 and descricao == "Impostos do mês") or (atras == 1 and descricao in ("Produtos de limpeza", "Combustível"))
            lancar(atras, descricao, categoria, v, dia, mes, fornecedor, servico, aberta=aberta)
    for atras, descricao, categoria, valor, dia in PONTUAIS:
        lancar(atras, descricao, categoria, valor, dia, meses[len(meses) - 1 - atras], "Fornecedor Exemplo")

    # Contas a vencer nos próximos dias (hoje, 7 e 30 dias), para a tela "Contas a pagar".
    for descricao, categoria, valor, dias in [
        ("Seguro do galpão", "Outros", 380, 0), ("Manutenção do ar-condicionado", "Manutenção", 260, 4),
        ("Licença de software", "Equipamentos", 190, 12), ("Taxa anual do sindicato", "Impostos e taxas", 450, 25),
    ]:
        d = hoje + timedelta(days=dias)
        lancar(0, descricao, categoria, valor, d.day, d, "Fornecedor Exemplo", aberta=True)

    RegistroAuditoria.objects.bulk_create([
        RegistroAuditoria(entidade=Entidade.DESPESA, objeto_id=d.pk, acao="criado",
                          descricao=f"Despesa criada: {d.descricao} (dados fictícios).", usuario=admin)
        for d in criadas])

    regras.gerar_recorrentes(hoje)  # as fixas dos próximos meses (sem duplicar as já criadas)

    # Meses antigos fechados: nada neles pode mais ser criado, editado ou estornado.
    for atras in (4, 3):
        mes = meses[len(meses) - 1 - atras]
        FechamentoMes.objects.create(mes=mes, fechado=True, fechado_por=admin, fechado_em=timezone.now())
        regras.auditar(Entidade.MES, mes.year * 100 + mes.month, "fechado", f"Mês {mes:%m/%Y} fechado.", admin)
    return len(criadas)
