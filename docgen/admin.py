from django.contrib import admin
from .models import Template, DocumentoGerado, Setor, Area, Categoria

# Permite gerenciar Setores, Áreas e Categorias no painel
admin.site.register(Setor)
admin.site.register(Area)
admin.site.register(Categoria)

@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    # Adicionei 'get_categoria_nome' na lista para aparecer na coluna
    list_display = ('titulo', 'get_setor_nome', 'get_area_nome', 'get_categoria_nome', 'ativo', 'data_criacao')
    
    # Adicionei filtros laterais para tudo
    list_filter = ('setor', 'categoria', 'ativo') 
    
    search_fields = ('titulo',)

    # --- Funções para mostrar nomes bonitos na tabela ---

    def get_setor_nome(self, obj):
        return obj.setor.nome
    get_setor_nome.short_description = 'Setor'

    def get_area_nome(self, obj):
        return obj.area.nome if obj.area else '-'
    get_area_nome.short_description = 'Área'

    def get_categoria_nome(self, obj):
        return obj.categoria.nome if obj.categoria else '-'
    get_categoria_nome.short_description = 'Tipo de Documento'

@admin.register(DocumentoGerado)
class DocumentoGeradoAdmin(admin.ModelAdmin):
    list_display = ('template', 'usuario', 'data_geracao')
    list_filter = ('usuario', 'data_geracao') # Útil para ver produção por usuário