from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

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

# Configuração dos Metadados da Documentação
schema_view = get_schema_view(
   openapi.Info(
      title="DunaDoc API",
      default_version='v1',
      description="API de Automação de Documentos Jurídicos do MDR Advocacia.",
      terms_of_service="https://www.google.com/policies/terms/",
      contact=openapi.Contact(email="ti@mdradvocacia.com.br"),
      license=openapi.License(name="BSD License"),
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('docgen.urls')), # Suas rotas do app
    
    # --- ROTAS DE DOCUMENTAÇÃO (SWAGGER) ---
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]