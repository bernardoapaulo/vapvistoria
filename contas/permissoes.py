"""
Definição dos perfis (grupos) e de suas permissões.

- Administrador: todas as permissões (cadastros, tipos de serviço, atendimentos,
  agenda, incluindo valor/desconto, reabrir, excluir e horário de funcionamento).
- Funcionário: gerencia clientes, alunos e veículos; cria, edita e muda o status
  de atendimentos e de agendamentos (sem alterar valor/desconto, reabrir ou
  excluir); vê a agenda de todos; apenas CONSULTA os tipos de serviço.

- Financeiro: tudo é do Administrador. O Funcionário só tem `financeiro.add_recebimento` (registrar
  recebimento na tela do atendimento); não vê o módulo, totais, despesas, nem estorna/edita.
"""
from django.contrib.auth.models import Group, Permission

ADMINISTRADOR = "Administrador"
FUNCIONARIO = "Funcionário"

TODAS = ["view", "add", "change", "delete"]
CADASTROS_COMPLETOS = ["cliente", "aluno", "veiculo"]
SOMENTE_CONSULTA = ["tiposervico"]

# Permissões personalizadas (definidas nos modelos)
ATENDIMENTO_EXTRAS = ["alterar_valor", "reabrir", "ver_faturamento", "exportar_dados"]
AGENDAMENTO_EXTRAS = ["reabrir"]
RECEBIMENTO_EXTRAS = ["ver_financeiro", "estornar_recebimento"]


def _permissoes(modelos, acoes):
    codenames = [f"{acao}_{modelo}" for modelo in modelos for acao in acoes]
    return list(Permission.objects.filter(codename__in=codenames))


def _permissoes_do_app(app, modelo, acoes, extras=()):
    """Permissões de um modelo de um app específico (evita confundir nomes iguais)."""
    return list(Permission.objects.filter(
        content_type__app_label=app, content_type__model=modelo,
        codename__in=[f"{a}_{modelo}" for a in acoes] + list(extras),
    ))


def criar_grupos():
    """Cria (ou atualiza) os grupos e suas permissões. Pode rodar várias vezes."""
    admin, _ = Group.objects.get_or_create(name=ADMINISTRADOR)
    admin.permissions.set(
        _permissoes(CADASTROS_COMPLETOS + SOMENTE_CONSULTA, TODAS)
        + _permissoes_do_app("atendimentos", "atendimento", TODAS, ATENDIMENTO_EXTRAS)
        + _permissoes_do_app("agenda", "agendamento", TODAS, AGENDAMENTO_EXTRAS)
        + _permissoes_do_app("agenda", "horariofuncionamento", ["view", "change"])
        # Financeiro: só o Administrador. Recebimento nunca é excluído (só estornado).
        + _permissoes_do_app("financeiro", "recebimento", ["view", "add", "change"], RECEBIMENTO_EXTRAS)
        + _permissoes_do_app("financeiro", "despesa", TODAS)
        + _permissoes_do_app("financeiro", "categoriadespesa", TODAS)
        + _permissoes_do_app("financeiro", "fechamentomes", ["view"], ["fechar_mes"])
    )

    func, _ = Group.objects.get_or_create(name=FUNCIONARIO)
    func.permissions.set(
        _permissoes(CADASTROS_COMPLETOS, TODAS)
        + _permissoes(SOMENTE_CONSULTA, ["view"])
        + _permissoes_do_app("atendimentos", "atendimento", ["view", "add", "change"])
        + _permissoes_do_app("agenda", "agendamento", ["view", "add", "change"])
        # Única exceção no Financeiro: registrar um recebimento na tela do atendimento (caixa do dia a dia).
        + _permissoes_do_app("financeiro", "recebimento", ["add"])
    )
    return admin, func
