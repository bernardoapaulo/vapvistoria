from django.core.management.base import BaseCommand

from contas.permissoes import criar_grupos


class Command(BaseCommand):
    help = "Cria/atualiza os grupos Administrador e Funcionário com suas permissões."

    def handle(self, *args, **options):
        criar_grupos()
        self.stdout.write(self.style.SUCCESS("Grupos e permissões atualizados."))
