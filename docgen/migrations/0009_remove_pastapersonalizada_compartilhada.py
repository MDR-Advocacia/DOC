# Remove o campo legado `compartilhada` — agora derivado de `nivel_acesso != 'privado'`.
# Não há perda de informação: o valor de `compartilhada` era sempre sincronizado
# com `nivel_acesso` por `apply_folder_permissions`.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('docgen', '0008_remove_processos_module'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='pastapersonalizada',
            name='compartilhada',
        ),
    ]
