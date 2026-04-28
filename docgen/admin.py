from django.contrib import admin

from .models import (
    Area,
    ArquivoArmazenado,
    ArquivoProcesso,
    Categoria,
    DocumentoGerado,
    Equipe,
    ExecucaoCapturaProcesso,
    LoteImportacaoProcessos,
    PastaPersonalizada,
    Processo,
    Setor,
    Template,
)


admin.site.register(Setor)
admin.site.register(Area)
admin.site.register(Categoria)


@admin.register(Equipe)
class EquipeAdmin(admin.ModelAdmin):
    list_display = ('nome', 'equipe_pai', 'criada_em')
    search_fields = ('nome',)
    filter_horizontal = ('supervisores', 'membros')


@admin.register(PastaPersonalizada)
class PastaPersonalizadaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'escopo', 'nivel_acesso', 'usuario', 'pasta_pai', 'compartilhada', 'criado_em')
    list_filter = ('escopo', 'nivel_acesso', 'compartilhada')
    search_fields = ('nome', 'usuario__username')
    filter_horizontal = ('equipes_permitidas', 'usuarios_permitidos')


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'get_setor_nome', 'get_area_nome', 'get_categoria_nome', 'ativo', 'data_criacao')
    list_filter = ('setor', 'categoria', 'ativo')
    search_fields = ('titulo',)

    def get_setor_nome(self, obj):
        return obj.setor.nome

    get_setor_nome.short_description = 'Setor'

    def get_area_nome(self, obj):
        return obj.area.nome if obj.area else '-'

    get_area_nome.short_description = 'Area'

    def get_categoria_nome(self, obj):
        return obj.categoria.nome if obj.categoria else '-'

    get_categoria_nome.short_description = 'Tipo de Documento'


@admin.register(DocumentoGerado)
class DocumentoGeradoAdmin(admin.ModelAdmin):
    list_display = ('template', 'usuario', 'data_geracao')
    list_filter = ('usuario', 'data_geracao')


@admin.register(Processo)
class ProcessoAdmin(admin.ModelAdmin):
    list_display = ('numero_cnj', 'usuario', 'tribunal_codigo', 'status_atual', 'ultimo_sucesso_em', 'atualizado_em')
    list_filter = ('status_atual', 'tribunal_codigo')
    search_fields = ('numero_cnj', 'usuario__username', 'referencia_interna')


@admin.register(ExecucaoCapturaProcesso)
class ExecucaoCapturaProcessoAdmin(admin.ModelAdmin):
    list_display = ('processo', 'status', 'worker_id', 'tentativa', 'criado_em', 'finalizada_em')
    list_filter = ('status', 'worker_id', 'criado_em')
    search_fields = ('processo__numero_cnj', 'processo__usuario__username', 'mensagem')


@admin.register(ArquivoProcesso)
class ArquivoProcessoAdmin(admin.ModelAdmin):
    list_display = ('processo', 'tipo', 'atual', 'checksum', 'criado_em')
    list_filter = ('tipo', 'atual', 'criado_em')
    search_fields = ('processo__numero_cnj', 'checksum')


@admin.register(ArquivoArmazenado)
class ArquivoArmazenadoAdmin(admin.ModelAdmin):
    list_display = ('nome_original', 'tipo', 'pasta', 'usuario', 'tamanho_bytes', 'criado_em')
    list_filter = ('tipo', 'pasta')
    search_fields = ('nome_original', 'descricao', 'usuario__username')


@admin.register(LoteImportacaoProcessos)
class LoteImportacaoProcessosAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario', 'total_linhas', 'total_processos_criados', 'total_processos_atualizados', 'criado_em')
    list_filter = ('criado_em',)
    search_fields = ('usuario__username',)
