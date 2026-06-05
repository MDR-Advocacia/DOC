from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions


schema_view = get_schema_view(
    openapi.Info(
        title="DunaDoc API",
        default_version='v1',
        description="API de automacao de documentos juridicos do MDR Advocacia.",
        terms_of_service="https://www.google.com/policies/terms/",
        contact=openapi.Contact(email="ti@mdradvocacia.com.br"),
        license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)


def healthz(_request):
    """Endpoint leve para healthcheck do Coolify/Docker.

    Não toca no banco para não falhar deploy quando o Postgres ainda está
    inicializando. Quem quiser checar dependências usa /readyz/ (futuro).
    """
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path('admin/', admin.site.urls),
    path('calculadora/', include('calculadora.urls')),
    path('', include('docgen.urls')),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]


# Serve arquivos de mídia (templates DOCX, documentos gerados) também em
# produção. Pra baixo volume de tráfego (escritório pequeno) é aceitável o
# Django/Gunicorn servir direto. Atenção: arquivos ficam públicos via URL —
# pendência: trocar por view dedicada com @login_required + FileResponse.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
