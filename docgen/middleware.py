"""Middleware que cobra o vínculo com o Entra ID uma única vez."""

from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

# Caminhos que precisam continuar acessíveis enquanto a pessoa não vinculou —
# senão ela não conseguiria nem fazer o vínculo, nem sair.
ISENTOS = (
    '/vincular-entra-id/',
    '/accounts/sso/',
    '/accounts/logout/',
    '/accounts/login/',
    '/static/',
    '/media/',
    '/healthz/',
    '/admin/',
)

CHAVE_SESSAO = 'entra_vinculado'


class ExigirVinculoEntraIdMiddleware:
    """Redireciona quem entrou com senha e ainda não provou a conta corporativa.

    Cobra uma vez só: assim que o vínculo existe, a sessão é marcada e nem a
    consulta ao banco acontece mais. Se a pessoa não conseguir concluir (não
    tem conta no Entra, por exemplo), nada é bloqueado à força — ela será
    convidada de novo no próximo acesso, em vez de ficar trancada para fora.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._deve_cobrar(request):
            return redirect(reverse('vincular_entra'))
        return self.get_response(request)

    def _deve_cobrar(self, request) -> bool:
        if not getattr(settings, 'SSO_ENABLED', False):
            return False
        if not getattr(settings, 'ENTRA_VINCULO_OBRIGATORIO', True):
            return False
        usuario = getattr(request, 'user', None)
        if usuario is None or not usuario.is_authenticated:
            return False
        if request.session.get(CHAVE_SESSAO):
            return False
        if any(request.path.startswith(p) for p in ISENTOS):
            return False

        if hasattr(usuario, 'vinculo_entra'):
            request.session[CHAVE_SESSAO] = True
            return False
        return True
