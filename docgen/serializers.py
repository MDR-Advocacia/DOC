from rest_framework import serializers

from .models import DocumentoGerado, Template


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = ['id', 'titulo', 'descricao', 'data_criacao', 'categoria', 'setor', 'area']


class DocumentoSerializer(serializers.ModelSerializer):
    template_nome = serializers.CharField(source='template.titulo', read_only=True)

    class Meta:
        model = DocumentoGerado
        fields = ['id', 'template', 'template_nome', 'arquivo_final', 'data_geracao', 'usuario']
