from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Painel Administrativo
    path('admin/', admin.site.urls),
    
    # Sistema de Login/Logout padrão do Django
    path('accounts/', include('django.contrib.auth.urls')),
    
    # Inclui as rotas do nosso aplicativo DOCGEN
    path('', include('docgen.urls')),
]

# --- Configuração para servir arquivos de mídia (Downloads) no modo DEBUG ---
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)