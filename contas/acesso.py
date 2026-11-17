"""
Central de acesso por módulo: UM lugar que diz quais módulos cada perfil enxerga.

O mapa por perfil fica em `contas/permissoes.py` (ACESSO_POR_PERFIL). Aqui ficam o registro dos módulos (nome ->
prefixos de URL), as funções de consulta, o middleware que BLOQUEIA no servidor e o context processor que o menu e os
templates usam (`modulos.agenda`, `pagina_inicial_url`). Reabilitar um módulo para o Funcionário = acrescentar o nome
dele em ACESSO_POR_PERFIL[FUNCIONARIO]; nenhuma view nem template muda.

Duas camadas valem juntas: o módulo precisa estar liberado no mapa E o usuário precisa ter a permissão do Django
(as permissões dos grupos continuam no banco; ocultar um módulo não apaga nada).
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from . import permissoes

# nome do módulo -> prefixos de URL que pertencem a ele (tudo sob o prefixo: telas, JSON, CSV, downloads...)
MODULOS = {
    "clientes": ("/clientes/",),
    "alunos": ("/alunos/",),
    "veiculos": ("/veiculos/",),
    "servicos": ("/servicos/",),
    "atendimentos": ("/atendimentos/",),
    "agenda": ("/agenda/",),
    "dashboard": ("/dashboard/",),
    "financeiro": ("/financeiro/",),
    "vip": ("/vip/",),
    "admin": ("/admin/",),
}
# "inicio" ("/") não é barrado por prefixo: o perfil sem Início é redirecionado à sua página inicial.
NOMES = ("inicio",) + tuple(MODULOS)
ROTAS_PUBLICAS = ("", "entrar/", "sair/")   # login, logout e a própria raiz: não pertencem a módulo


def _mapa():
    return getattr(settings, "ACESSO_POR_PERFIL", permissoes.ACESSO_POR_PERFIL)


def _paginas_iniciais():
    return getattr(settings, "PAGINA_INICIAL_POR_PERFIL", permissoes.PAGINA_INICIAL_POR_PERFIL)


def modulos_do_usuario(user):
    """Conjunto de módulos que o usuário enxerga (soma dos perfis a que ele pertence)."""
    if not user.is_authenticated:
        return frozenset()
    if user.is_superuser:
        return frozenset(NOMES)
    em_cache = getattr(user, "_modulos_acesso", None)
    if em_cache is not None:
        return em_cache
    mapa, conjunto = _mapa(), set()
    for nome in user.groups.values_list("name", flat=True):
        liberados = mapa.get(nome, ())
        conjunto |= set(NOMES) if liberados == permissoes.TODOS_OS_MODULOS else set(liberados)
    user._modulos_acesso = frozenset(conjunto)
    return user._modulos_acesso


def pode_acessar(user, modulo):
    return modulo in modulos_do_usuario(user)


def modulo_da_url(caminho):
    for modulo, prefixos in MODULOS.items():
        if any(caminho.startswith(p) for p in prefixos):
            return modulo
    return None


def pagina_inicial(user):
    """Nome da URL para onde o usuário vai ao entrar (ou ao abrir "/")."""
    if pode_acessar(user, "inicio") or not modulos_do_usuario(user):
        return "inicio"   # sem nenhum módulo mapeado (ex.: sem perfil): a página inicial simples de sempre
    for nome in user.groups.values_list("name", flat=True):
        destino = _paginas_iniciais().get(nome)
        if destino:
            return destino
    return "inicio"


class AcessoPorModuloMiddleware:
    """Barra no servidor qualquer endereço de um módulo que o perfil não enxerga (403 com a identidade da empresa)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            modulo = modulo_da_url(request.path)
            if modulo and not pode_acessar(user, modulo):
                raise PermissionDenied(f"Módulo '{modulo}' não liberado para este perfil.")
        return self.get_response(request)


def contexto_acesso(request):
    """Para os templates: {% if modulos.agenda %} e o link da página inicial do perfil."""
    user = request.user
    liberados = modulos_do_usuario(user)
    return {
        "modulos": {nome: nome in liberados for nome in NOMES},
        "pagina_inicial_url": reverse(pagina_inicial(user)) if user.is_authenticated else reverse("login"),
    }
