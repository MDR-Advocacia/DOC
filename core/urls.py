from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('docgen.urls')),
]

# Adicione isso para que, enquanto estamos desenvolvendo, 
# o Django consiga abrir os arquivos Word que você subir.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)