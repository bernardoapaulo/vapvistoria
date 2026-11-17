"""
Build na Vercel: aplica as migrações e, se pedido, carrega os dados fictícios ou limpa os dados de teste.

Para carregar os dados fictícios no site publicado, defina na Vercel (Settings > Environment Variables):
  CARREGAR_DADOS_FICTICIOS=1, SENHA_ADMIN_TESTE e SENHA_FUNCIONARIO_TESTE (senhas suas, não as do README)
e faça Redeploy. Depois de carregar, pode apagar CARREGAR_DADOS_FICTICIOS (rodar de novo não duplica nada).

Para LIMPAR os dados de teste e deixar o site pronto para uso, defina LIMPAR_DADOS_TESTE=SIM e faça Redeploy.
O comando só age se os dados fictícios ainda existirem (limpar_dados_teste --somente-se-ficticio): depois de limpo,
deixar a variável ligada não apaga nada. Apague-a mesmo assim, e NÃO deixe CARREGAR_DADOS_FICTICIOS ligada junto.
"""
import os

import django
from django.core.management import call_command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

call_command("migrate", interactive=False)
if os.environ.get("LIMPAR_DADOS_TESTE") == "SIM":
    call_command("limpar_dados_teste", confirmar=True, somente_se_ficticio=True)
elif os.environ.get("CARREGAR_DADOS_FICTICIOS") == "1":
    call_command("popular_dados")
