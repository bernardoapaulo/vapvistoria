"""
Build na Vercel: aplica as migrações e, se pedido, carrega os dados fictícios e os usuários de teste.

Para carregar os dados no site publicado, defina na Vercel (Settings > Environment Variables):
  CARREGAR_DADOS_FICTICIOS=1, SENHA_ADMIN_TESTE e SENHA_FUNCIONARIO_TESTE (senhas suas, não as do README)
e faça Redeploy. Depois de carregar, pode apagar CARREGAR_DADOS_FICTICIOS (rodar de novo não duplica nada).
"""
import os

import django
from django.core.management import call_command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

call_command("migrate", interactive=False)
if os.environ.get("CARREGAR_DADOS_FICTICIOS") == "1":
    call_command("popular_dados")
