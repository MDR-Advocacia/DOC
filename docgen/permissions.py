import secrets

from django.conf import settings
from rest_framework import permissions

class IsDonoDoDocumento(permissions.BasePermission):
    """
    Permissão personalizada para permitir que apenas o dono do documento o acesse.
    """

    def has_object_permission(self, request, view, obj):
        # Métodos de leitura segura (GET, HEAD, OPTIONS) são permitidos?
        # Se quiser que outros vejam mas não editem, descomente a linha abaixo:
        # if request.method in permissions.SAFE_METHODS: return True

        # Apenas o dono do objeto pode ver ou editar
        return obj.usuario == request.user


class HasWorkerToken(permissions.BasePermission):
    message = "Token interno do worker invalido."

    def has_permission(self, request, view):
        expected_token = (getattr(settings, 'PROCESSOS_WORKER_TOKEN', '') or '').strip()
        if not expected_token:
            return False

        auth_header = request.headers.get('Authorization', '')
        token = ''
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
        if not token:
            token = request.headers.get('X-Worker-Token', '').strip()

        return bool(token) and secrets.compare_digest(token, expected_token)
