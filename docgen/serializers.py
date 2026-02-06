from rest_framework import serializers
from .models import Template, DocumentoGerado  # <--- Nome correto aqui

class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = ['id', 'titulo', 'descricao', 'criado_em']

class DocumentoSerializer(serializers.ModelSerializer):
    template_nome = serializers.CharField(source='template.titulo', read_only=True)
    
    class Meta:
        model = DocumentoGerado  # <--- Nome correto aqui
        # Ajustei os campos para bater com o seu print:
        fields = ['id', 'template', 'template_nome', 'arquivo_final', 'data_geracao', 'usuario']