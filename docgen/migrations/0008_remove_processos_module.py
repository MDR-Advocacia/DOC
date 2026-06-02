# Migration de remoção do módulo de processos.
# Apaga índices, constraints e os 4 modelos (Processo, LoteImportacaoProcessos,
# ExecucaoCapturaProcesso, ArquivoProcesso). Gerada por makemigrations e renomeada
# para refletir intenção.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('docgen', '0007_pastas_escopo_permissoes_repositorio'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='arquivoprocesso',
            name='uniq_arquivo_processo_atual_por_tipo',
        ),
        migrations.RemoveIndex(
            model_name='execucaocapturaprocesso',
            name='docgen_exec_status_30d4cd_idx',
        ),
        migrations.RemoveField(
            model_name='loteimportacaoprocessos',
            name='usuario',
        ),
        migrations.RemoveIndex(
            model_name='processo',
            name='docgen_proc_status__e23b69_idx',
        ),
        migrations.RemoveConstraint(
            model_name='processo',
            name='uniq_processo_usuario_numero_cnj',
        ),
        migrations.RemoveField(
            model_name='execucaocapturaprocesso',
            name='lote',
        ),
        migrations.RemoveField(
            model_name='execucaocapturaprocesso',
            name='processo',
        ),
        migrations.RemoveField(
            model_name='processo',
            name='usuario',
        ),
        migrations.DeleteModel(
            name='ArquivoProcesso',
        ),
        migrations.DeleteModel(
            name='LoteImportacaoProcessos',
        ),
        migrations.DeleteModel(
            name='ExecucaoCapturaProcesso',
        ),
        migrations.DeleteModel(
            name='Processo',
        ),
    ]
