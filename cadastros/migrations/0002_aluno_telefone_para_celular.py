from django.db import migrations


class Migration(migrations.Migration):
    """Renomeia telefone -> celular preservando os dados dos alunos já cadastrados."""

    dependencies = [("cadastros", "0001_initial")]

    operations = [
        migrations.RenameField("aluno", "telefone", "celular"),
    ]
