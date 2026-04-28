from rest_framework import serializers

from .models import DocumentoGerado, ExecucaoCapturaProcesso, Processo, Template


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = ['id', 'titulo', 'descricao', 'data_criacao', 'categoria', 'setor', 'area']


class DocumentoSerializer(serializers.ModelSerializer):
    template_nome = serializers.CharField(source='template.titulo', read_only=True)

    class Meta:
        model = DocumentoGerado
        fields = ['id', 'template', 'template_nome', 'arquivo_final', 'data_geracao', 'usuario']


class ProcessoSerializer(serializers.ModelSerializer):
    usuario_email = serializers.CharField(source='usuario.username', read_only=True)
    status_label = serializers.CharField(source='get_status_atual_display', read_only=True)

    class Meta:
        model = Processo
        fields = [
            'id',
            'numero_cnj',
            'tribunal_codigo',
            'tribunal_nome',
            'status_atual',
            'status_label',
            'ultima_mensagem',
            'usuario_email',
            'referencia_interna',
            'observacao',
            'ultimo_sucesso_em',
        ]


class ExecucaoCapturaProcessoSerializer(serializers.ModelSerializer):
    processo = ProcessoSerializer(read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ExecucaoCapturaProcesso
        fields = [
            'id',
            'processo',
            'status',
            'status_label',
            'worker_id',
            'tentativa',
            'iniciada_em',
            'finalizada_em',
            'heartbeat_em',
            'mensagem',
            'tribunal_url',
            'lote_id',
        ]
