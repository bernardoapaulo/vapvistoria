"""
Painel /admin/: é por aqui que o Administrador cadastra os usuários (login e senha) e escolhe o perfil (grupo).

Quem não é superusuário (o Administrador comum) pode ver, criar e alterar usuários, mas não consegue se dar
poderes a mais: os campos "superusuário" e "permissões individuais" ficam somente leitura e superusuários não são
editáveis por ele. Excluir usuário não é permitido (desative com "Ativo" e o histórico continua guardado).
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

Usuario = get_user_model()

if admin.site.is_registered(Usuario):
    admin.site.unregister(Usuario)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "email", "perfis", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "groups")

    @admin.display(description="Perfis")
    def perfis(self, obj):
        return ", ".join(g.name for g in obj.groups.all()) or "—"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    def get_readonly_fields(self, request, obj=None):
        somente_leitura = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            somente_leitura = (*somente_leitura, "is_superuser", "user_permissions", "last_login", "date_joined")
        return somente_leitura

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False        # um Administrador comum não mexe em superusuários
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser     # desative em vez de excluir
