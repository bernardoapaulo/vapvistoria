from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _criar_grupos(sender, **kwargs):
    # Garante que as permissões de todos os apps já existam antes de montar os grupos.
    from django.apps import apps
    from django.contrib.auth.management import create_permissions

    for app_config in apps.get_app_configs():
        if app_config.models_module is not None:
            create_permissions(app_config, verbosity=0)

    from .permissoes import criar_grupos
    criar_grupos()


class ContasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contas"
    verbose_name = "Contas e perfis"

    def ready(self):
        # Após cada "migrate", os grupos Administrador e Funcionário são (re)criados.
        post_migrate.connect(_criar_grupos, sender=self)
