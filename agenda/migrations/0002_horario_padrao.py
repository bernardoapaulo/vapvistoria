from datetime import time

from django.db import migrations

# (dia da semana 0=segunda, aberto, abre, fecha)
PADRAO = [
    (0, True, time(8, 0), time(18, 0)),
    (1, True, time(8, 0), time(18, 0)),
    (2, True, time(8, 0), time(18, 0)),
    (3, True, time(8, 0), time(18, 0)),
    (4, True, time(8, 0), time(18, 0)),
    (5, True, time(8, 0), time(12, 0)),
    (6, False, None, None),
]


def criar_horario_padrao(apps, schema_editor):
    Horario = apps.get_model("agenda", "HorarioFuncionamento")
    for dia, aberto, abre, fecha in PADRAO:
        Horario.objects.get_or_create(dia_semana=dia, defaults={"aberto": aberto, "abre": abre, "fecha": fecha})


class Migration(migrations.Migration):
    dependencies = [("agenda", "0001_initial")]
    operations = [migrations.RunPython(criar_horario_padrao, migrations.RunPython.noop)]
