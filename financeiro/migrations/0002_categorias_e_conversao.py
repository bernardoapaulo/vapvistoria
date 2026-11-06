from django.db import migrations

from financeiro.migracao_pagamentos import converter_pagamentos, criar_categorias


class Migration(migrations.Migration):
    """Cria as categorias de despesa padrão e converte os pagamentos da etapa 2 em recebimentos."""

    dependencies = [
        ("financeiro", "0001_inicial"),
        ("atendimentos", "0004_pagamento_a_revisar"),
    ]

    operations = [
        migrations.RunPython(criar_categorias, migrations.RunPython.noop),
        migrations.RunPython(converter_pagamentos, migrations.RunPython.noop),
    ]
