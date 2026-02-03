from django.contrib import admin
from .models import Template, DocumentoGerado, Setor, Area

# Permite gerenciar Setores e Áreas
admin.site.register(Setor)
admin.site.register(Area)

@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'get_setor_nome', 'get_area_nome', 'ativo', 'data_criacao')
    list_filter = ('setor', 'ativo') # Agora o filtro usa os setores do banco
    search_fields = ('titulo',)

    # Truque para mostrar o nome bonito na tabela, já que agora é uma relação
    def get_setor_nome(self, obj):
        return obj.setor.nome
    get_setor_nome.short_description = 'Setor'

    def get_area_nome(self, obj):
        return obj.area.nome if obj.area else '-'
    get_area_nome.short_description = 'Área'

@admin.register(DocumentoGerado)
class DocumentoGeradoAdmin(admin.ModelAdmin):
    list_display = ('template', 'usuario', 'data_geracao')