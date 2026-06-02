from rest_framework import permissions


class IsDonoDoDocumento(permissions.BasePermission):
    """Permite acesso apenas ao usuário dono do objeto (campo `usuario`)."""

    def has_object_permission(self, request, view, obj):
        return obj.usuario == request.user
