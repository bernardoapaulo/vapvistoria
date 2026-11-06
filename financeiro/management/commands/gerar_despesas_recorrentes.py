"""
Gera as despesas dos próximos meses a partir das marcadas como "repetir todo mês".
Seguro para agendar (cron/Agendador de Tarefas): nunca duplica uma despesa já gerada.

Uso:  python manage.py gerar_despesas_recorrentes [--meses 2]
"""
from django.core.management.base import BaseCommand

from financeiro import regras


class Command(BaseCommand):
    help = "Gera as despesas recorrentes dos próximos meses (sem duplicar)."

    def add_arguments(self, parser):
        parser.add_argument("--meses", type=int, default=2, help="Quantos meses à frente gerar (padrão: 2).")

    def handle(self, *args, **options):
        criadas = regras.gerar_recorrentes(meses_a_frente=options["meses"])
        self.stdout.write(self.style.SUCCESS(f"{criadas} despesa(s) recorrente(s) criada(s)."))
