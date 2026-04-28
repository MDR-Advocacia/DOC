import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def sincronizar_pastas_compartilhadas(apps, schema_editor):
    PastaPersonalizada = apps.get_model('docgen', 'PastaPersonalizada')
    PastaPersonalizada.objects.filter(compartilhada=True).update(nivel_acesso='equipes')


class Migration(migrations.Migration):

    dependencies = [
        ('docgen', '0006_arquivoarmazenado'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='pastapersonalizada',
            name='escopo',
            field=models.CharField(
                choices=[('biblioteca', 'Biblioteca'), ('repositorio', 'Repositorio')],
                default='biblioteca',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='pastapersonalizada',
            name='nivel_acesso',
            field=models.CharField(
                choices=[
                    ('privado', 'Privada'),
                    ('equipes', 'Equipes'),
                    ('restrito', 'Usuarios selecionados'),
                ],
                default='privado',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='pastapersonalizada',
            name='usuarios_permitidos',
            field=models.ManyToManyField(blank=True, related_name='pastas_com_acesso', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='arquivoarmazenado',
            name='pasta',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='arquivos',
                to='docgen.pastapersonalizada',
            ),
        ),
        migrations.RunPython(sincronizar_pastas_compartilhadas, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='pastapersonalizada',
            index=models.Index(fields=['escopo', 'usuario'], name='docgen_pasta_esc_usuario_idx'),
        ),
        migrations.AddIndex(
            model_name='pastapersonalizada',
            index=models.Index(fields=['escopo', 'nivel_acesso'], name='docgen_pasta_esc_acesso_idx'),
        ),
    ]
