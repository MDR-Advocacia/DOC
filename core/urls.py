import os

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
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


@login_required
def media_protegida(request, filename):
    """Serve arquivos de MEDIA_ROOT apenas para usuários autenticados.

    Substitui o `static()` que só funciona com DEBUG=True. Garante que
    templates DOCX, documentos gerados e outros uploads não sejam baixáveis
    por qualquer um que adivinhe a URL.

    Não faz check de autorização granular — qualquer user logado acessa.
    Para arquivos com permissão por pasta (ArquivoArmazenado), continue
    usando a view dedicada `arquivo_download` em docgen, que verifica a
    permissão da PastaPersonalizada antes de servir.
    """
    # Bloqueia path traversal (`../`, paths absolutos).
    safe_rel = os.path.normpath(filename).replace('\\', '/').lstrip('/')
    if safe_rel.startswith('..') or os.path.isabs(safe_rel):
        raise Http404

    full_path = os.path.join(str(settings.MEDIA_ROOT), safe_rel)
    if not os.path.isfile(full_path):
        raise Http404

    # `as_attachment=False` mantém comportamento atual: o link já tem
    # `download` no HTML, e arquivos como imagens precisam abrir inline em
    # alguns contextos. O navegador respeita o atributo download.
    return FileResponse(open(full_path, 'rb'))


urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path('admin/', admin.site.urls),
    path('calculadora/', include('calculadora.urls')),
    path('', include('docgen.urls')),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    # Mídia (templates DOCX, documentos gerados etc) só para usuários logados.
    # MEDIA_URL é '/media/' por padrão; usamos lstrip pra não ficar '//media/'
    # quando alguém configurar com leading slash.
    path(
        settings.MEDIA_URL.lstrip('/') + '<path:filename>',
        media_protegida,
        name='media_protegida',
    ),
]
