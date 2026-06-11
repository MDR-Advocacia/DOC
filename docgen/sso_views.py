"""Login via Microsoft Entra ID (SSO) — espelha o approach do Flow, adaptado ao
Django (sessão em vez de JWT).

Fluxo:
1. Usuário clica em "Entrar com Microsoft" → vai pra /accounts/sso/.
2. Se ainda não tem sessão do oauth2-proxy, a view redireciona pro
   /oauth2/start (Entra) e volta pra cá com o cookie .dunatecnologia.com.
3. A view valida o cookie SERVER-SIDE (chama settings.SSO_VALIDATE_URL =
   /oauth2/auth do oauth2-proxy, repassando o cookie) e lê e-mail + nome.
4. Acha-ou-cria o User do Django pelo e-mail e faz login por sessão.

Segurança: o oauth2-proxy valida o cookie assinado e só então devolve a
identidade — nada é forjável pelo cliente. A senha (LoginView) continua
funcionando em paralelo.
"""
import base64
import json
import logging
import urllib.error
import urllib.request
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_backends, login
from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import redirect, render

logger = logging.getLogger(__name__)


def _name_from_id_token(authorization: str):
    """Extrai o claim `name` do ID token (Authorization: Bearer <jwt>) que o
    oauth2-proxy injeta quando OAUTH2_PROXY_SET_AUTHORIZATION_HEADER=true.
    Decodifica só o payload, sem verificar assinatura (vem do proxy confiável)."""
    raw = (authorization or "").strip()
    for prefix in ("Bearer ", "bearer "):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
            break
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    try:
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        name = (claims.get("name") or "").strip()
        return name or None
    except Exception:
        return None


def _validate_via_oauth2_proxy(cookie: str):
    """Valida a sessão do oauth2-proxy chamando settings.SSO_VALIDATE_URL com o
    cookie do usuário. Retorna (email, id_token) ou (None, '')."""
    url = getattr(settings, "SSO_VALIDATE_URL", "")
    if not url or not cookie:
        return None, ""
    try:
        req = urllib.request.Request(url, headers={"Cookie": cookie}, method="GET")
        with urllib.request.urlopen(req, timeout=6) as resp:
            email = (resp.headers.get(settings.SSO_EMAIL_HEADER) or "").strip().lower()
            id_token = resp.headers.get("Authorization") or ""
            return (email or None), id_token
    except urllib.error.HTTPError:
        # 401/403 → sem sessão SSO válida.
        return None, ""
    except Exception:
        logger.warning("Falha ao validar sessao SSO no oauth2-proxy", exc_info=True)
        return None, ""


def sso_login(request):
    if not getattr(settings, "SSO_ENABLED", False):
        raise Http404("SSO desativado")

    email, id_token = _validate_via_oauth2_proxy(request.META.get("HTTP_COOKIE", ""))

    if not email:
        # Sem sessão Entra → manda pro oauth2-proxy, que autentica e volta pra cá.
        # Força https no rd: atrás do Traefik, sem DJANGO_SECURE_PROXY o Django
        # acha que é http e o oauth2-proxy rejeita o rd http (cai na tela
        # estática "Authenticated" sem voltar pro app).
        base = getattr(settings, "SSO_AUTHORIZE_BASE", "").rstrip("/")
        rd = f"https://{request.get_host()}/accounts/sso/"
        return redirect(f"{base}/oauth2/start?rd={quote(rd, safe='')}")

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        # Acha-ou-cria (JIT). Conta nova nasce PENDENTE (is_active=False): cai na
        # tela de boas-vindas e aparece pro admin em "Gerenciar Usuários" pra
        # liberar — reusa o fluxo de aprovação que o DOC já tem.
        nome = _name_from_id_token(id_token) or email.split("@")[0]
        partes = nome.split(" ", 1)
        user = User(
            username=email[:150],
            email=email,
            first_name=partes[0][:30],
            last_name=(partes[1] if len(partes) > 1 else "")[:150],
            is_active=False,
        )
        user.set_unusable_password()
        user.save()

    if not user.is_active:
        # Conta nova ou ainda não aprovada → tela de boas-vindas (não loga).
        # O admin libera em Gerenciar Usuários (pendentes); aí o usuário entra.
        return render(request, "registration/sso_aguardando.html", {
            "nome": user.get_full_name() or user.first_name or email.split("@")[0],
            "email": email,
        })

    # login() exige um backend. Não usamos authenticate() (não há senha), então
    # carimbamos o backend padrão manualmente.
    backend = get_backends()[0]
    user.backend = f"{backend.__module__}.{backend.__class__.__name__}"
    login(request, user)
    return redirect("/")
