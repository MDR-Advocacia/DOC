from django.conf import settings
from django.db import migrations, models
import docgen.models


class Migration(migrations.Migration):

    dependencies = [
        ('docgen', '0005_loteimportacaoprocessos_processo_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ArquivoArmazenado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('arquivo', models.FileField(upload_to=docgen.models._upload_arquivo_armazenado)),
                ('nome_original', models.CharField(max_length=255)),
                ('tipo', models.CharField(choices=[('pdf', 'PDF'), ('xlsx', 'Excel (XLSX)'), ('csv', 'CSV'), ('outro', 'Outro')], default='outro', max_length=20)),
                ('descricao', models.TextField(blank=True)),
                ('tamanho_bytes', models.PositiveBigIntegerField(default=0)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('usuario', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='arquivos_armazenados', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-criado_em'],
                'indexes': [
                    models.Index(fields=['usuario', '-criado_em'], name='docgen_arq_usuario_29a1b6_idx'),
                    models.Index(fields=['tipo'], name='docgen_arq_tipo_2cd9f4_idx'),
                ],
            },
        ),
    ]
