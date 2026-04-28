from django.contrib import admin

from .models import CalculoCondenacaoCivel


@admin.register(CalculoCondenacaoCivel)
class CalculoCondenacaoCivelAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'usuario', 'status', 'possui_pdf', 'criado_em', 'atualizado_em')
    list_filter = ('status', 'criado_em', 'atualizado_em')
    search_fields = ('titulo', 'usuario__username')

    @admin.display(boolean=True, description='PDF')
    def possui_pdf(self, obj):
        return bool(obj.arquivo_sentenca_pdf)
