from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import Equipe, PastaPersonalizada


def team_memberships_for_user(user):
    if user.is_staff or user.is_superuser:
        return Equipe.objects.all()
    return Equipe.objects.filter(Q(membros=user) | Q(supervisores=user)).distinct()


def accessible_folders_queryset(user, escopo=None):
    qs = PastaPersonalizada.objects.all()
    if escopo:
        qs = qs.filter(escopo=escopo)

    if user.is_staff or user.is_superuser:
        return qs.distinct()

    equipes = team_memberships_for_user(user)
    return qs.filter(
        Q(usuario=user)
        | Q(nivel_acesso=PastaPersonalizada.ACESSO_EQUIPES, equipes_permitidas__in=equipes)
        | Q(compartilhada=True, equipes_permitidas__in=equipes)
        | Q(nivel_acesso=PastaPersonalizada.ACESSO_RESTRITO, usuarios_permitidos=user)
    ).distinct()


def editable_folders_queryset(user, escopo=None):
    qs = PastaPersonalizada.objects.all()
    if escopo:
        qs = qs.filter(escopo=escopo)

    if user.is_staff or user.is_superuser:
        return qs.distinct()
    return qs.filter(usuario=user).distinct()


def require_folder_editor(user, pasta):
    if user.is_staff or user.is_superuser or pasta.usuario_id == user.id:
        return
    raise PermissionDenied("Voce nao pode alterar esta pasta.")


def can_access_folder(user, pasta):
    if not pasta:
        return False
    if user.is_staff or user.is_superuser or pasta.usuario_id == user.id:
        return True
    if pasta.nivel_acesso == PastaPersonalizada.ACESSO_RESTRITO:
        return pasta.usuarios_permitidos.filter(id=user.id).exists()
    if pasta.nivel_acesso == PastaPersonalizada.ACESSO_EQUIPES or pasta.compartilhada:
        return pasta.equipes_permitidas.filter(
            Q(membros=user) | Q(supervisores=user)
        ).exists()
    return False


def normalize_access_level(user, nivel_acesso):
    allowed = {PastaPersonalizada.ACESSO_PRIVADO, PastaPersonalizada.ACESSO_EQUIPES}
    if user.is_staff or user.is_superuser:
        allowed.add(PastaPersonalizada.ACESSO_RESTRITO)

    nivel_acesso = nivel_acesso or PastaPersonalizada.ACESSO_PRIVADO
    if nivel_acesso not in allowed:
        raise PermissionDenied("Voce nao pode usar este nivel de permissao.")
    return nivel_acesso


def apply_folder_permissions(pasta, nivel_acesso, equipes=None, usuarios=None):
    equipes = equipes if equipes is not None else Equipe.objects.none()
    usuarios = usuarios if usuarios is not None else pasta.usuarios_permitidos.model.objects.none()

    pasta.nivel_acesso = nivel_acesso
    pasta.compartilhada = nivel_acesso != PastaPersonalizada.ACESSO_PRIVADO
    pasta.save(update_fields=['nivel_acesso', 'compartilhada'])

    if nivel_acesso == PastaPersonalizada.ACESSO_EQUIPES:
        pasta.equipes_permitidas.set(equipes)
        pasta.usuarios_permitidos.clear()
    elif nivel_acesso == PastaPersonalizada.ACESSO_RESTRITO:
        pasta.usuarios_permitidos.set(usuarios)
        pasta.equipes_permitidas.clear()
    else:
        pasta.equipes_permitidas.clear()
        pasta.usuarios_permitidos.clear()

    for subpasta in pasta.subpastas.all():
        apply_folder_permissions(subpasta, nivel_acesso, equipes, usuarios)


def copy_folder_permissions(origem, destino):
    destino.nivel_acesso = origem.nivel_acesso
    destino.compartilhada = origem.compartilhada
    destino.save(update_fields=['nivel_acesso', 'compartilhada'])
    destino.equipes_permitidas.set(origem.equipes_permitidas.all())
    destino.usuarios_permitidos.set(origem.usuarios_permitidos.all())
