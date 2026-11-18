"""
Definição dos perfis (grupos) e de suas permissões.

- Administrador: todas as permissões (cadastros, tipos de serviço, atendimentos,
  agenda, incluindo valor/desconto, reabrir, excluir e horário de funcionamento).
- Funcionário: gerencia clientes, alunos e veículos; cria, edita e muda o status
  de atendimentos e de agendamentos (sem alterar valor/desconto, reabrir ou
  excluir); vê a agenda de todos; consulta e CADASTRA tipos de serviço (não edita nem exclui).
  Essas permissões continuam no banco, mas hoje o Funcionário só enxerga Clientes, Serviços e Vip/Preparação
  (ver ACESSO_POR_PERFIL).

- Vip/Preparação: os dois perfis criam, editam, concluem (lança o recebimento), reabrem e excluem; só o
  Administrador altera o valor e edita um registro já concluído.
- Regravações: módulo só do Administrador (o Funcionário não o enxerga; ver o comentário em REGRAVACAO_EXTRAS_*).
- Usuários (/admin/): só o Administrador cadastra e altera (ver, criar e alterar; não exclui; não vira superusuário).
- Financeiro: tudo é do Administrador. O Funcionário só tem `financeiro.add_recebimento` (registrar
  recebimento na tela do atendimento); não vê o módulo, totais, despesas, nem estorna/edita.
"""
from django.contrib.auth.models import Group, Permission

ADMINISTRADOR = "Administrador"
FUNCIONARIO = "Funcionário"

# ---------------------------------------------------------------------------------------------------------------
# CENTRAL DE ACESSO: quais módulos cada perfil ENXERGA (menu, página inicial, links e bloqueio no servidor leem daqui).
# Módulos: inicio, clientes, alunos, veiculos, servicos, atendimentos, agenda, dashboard, financeiro, vip, admin.
# Para liberar de novo um módulo ao Funcionário, acrescente o nome dele na lista abaixo (ex.: "agenda"): é só isso.
# Ocultar NÃO apaga nada: código, dados e as permissões abaixo continuam como estão; vale módulo liberado E permissão.
# ---------------------------------------------------------------------------------------------------------------
TODOS_OS_MODULOS = "todos"
ACESSO_POR_PERFIL = {
    ADMINISTRADOR: TODOS_OS_MODULOS,
    FUNCIONARIO: ("clientes", "servicos", "vip"),
}
# Perfil sem o módulo "inicio": para onde vai ao entrar (nome da URL)
PAGINA_INICIAL_POR_PERFIL = {
    FUNCIONARIO: "vip_lista",
}

TODAS = ["view", "add", "change", "delete"]
CADASTROS_COMPLETOS = ["cliente", "aluno", "veiculo"]
SOMENTE_CONSULTA = ["tiposervico"]

# Permissões personalizadas (definidas nos modelos)
ATENDIMENTO_EXTRAS = ["alterar_valor", "reabrir", "ver_faturamento", "exportar_dados"]
AGENDAMENTO_EXTRAS = ["reabrir"]
RECEBIMENTO_EXTRAS = ["ver_financeiro", "estornar_recebimento"]
# Vip/Preparação: o que cada perfil pode além de ver/criar/editar/excluir (ajuste aqui)
VIP_EXTRAS_ADMINISTRADOR = ["alterar_valor_vip", "concluir_vip", "reabrir_vip", "editar_concluido_vip"]
VIP_EXTRAS_FUNCIONARIO = ["concluir_vip", "reabrir_vip"]
# Regravações: o Funcionário já tem as permissões "finas" abaixo guardadas no banco, mas o módulo fica OCULTO para ele
# (ver ACESSO_POR_PERFIL). Se você liberar "regravacoes" ao Funcionário: ele vê, cria, edita, conclui/recebe e emite
# documentos; NÃO altera valor, NÃO gerencia técnicos/parceiros/empresa, NÃO exclui, NÃO reabre e não edita o já lançado.
REGRAVACAO_EXTRAS_ADMINISTRADOR = ["alterar_valor_regravacao", "concluir_regravacao", "reabrir_regravacao",
                                   "emitir_documento_regravacao", "editar_lancada_regravacao"]
REGRAVACAO_EXTRAS_FUNCIONARIO = ["concluir_regravacao", "emitir_documento_regravacao"]


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
        + _permissoes_do_app("vip_preparacao", "registrovip", TODAS, VIP_EXTRAS_ADMINISTRADOR)
        # Usuários: o Administrador cadastra login e senha e escolhe o perfil em /admin/ (sem excluir; ver contas/admin.py)
        # Regravações: tudo (por padrão o módulo só aparece para o Administrador)
        + _permissoes_do_app("regravacoes", "registroregravacao", TODAS, REGRAVACAO_EXTRAS_ADMINISTRADOR)
        + _permissoes_do_app("regravacoes", "parceiro", TODAS, ["ver_faturamento_parceiro"])
        + _permissoes_do_app("regravacoes", "tecnico", TODAS)
        + _permissoes_do_app("regravacoes", "configuracaoempresa", ["view", "change"])
        + _permissoes_do_app("regravacoes", "documentoemitido", ["view"])
        + _permissoes_do_app("auth", "user", ["view", "add", "change"])
        + _permissoes_do_app("auth", "group", ["view"])
    )

    func, _ = Group.objects.get_or_create(name=FUNCIONARIO)
    func.permissions.set(
        _permissoes(CADASTROS_COMPLETOS, TODAS)
        + _permissoes(SOMENTE_CONSULTA, ["view", "add"])   # consulta e cadastra serviços; editar/excluir só o Administrador
        + _permissoes_do_app("atendimentos", "atendimento", ["view", "add", "change"])
        + _permissoes_do_app("agenda", "agendamento", ["view", "add", "change"])
        # Única exceção no Financeiro: registrar um recebimento na tela do atendimento (caixa do dia a dia).
        + _permissoes_do_app("financeiro", "recebimento", ["add"])
        + _permissoes_do_app("vip_preparacao", "registrovip", TODAS, VIP_EXTRAS_FUNCIONARIO)
        + _permissoes_do_app("regravacoes", "registroregravacao", ["view", "add", "change"], REGRAVACAO_EXTRAS_FUNCIONARIO)
        + _permissoes_do_app("regravacoes", "parceiro", ["view"])
        + _permissoes_do_app("regravacoes", "tecnico", ["view"])
        + _permissoes_do_app("regravacoes", "documentoemitido", ["view"])
    )
    return admin, func
