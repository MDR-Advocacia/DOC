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