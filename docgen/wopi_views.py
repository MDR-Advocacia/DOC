"""Endpoints WOPI + tela do editor Collabora.

Separado de views.py porque a natureza é outra: aqui quem chama é o servidor
do Collabora, autenticado por token na querystring, sem sessão e sem CSRF.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import wopi
from .models import DocumentoGerado

logger = logging.getLogger(__name__)

CONTENT_TYPE_DOCX = (
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
)


def _exige_flag():
    if not settings.COLLABORA_ENABLED:
        raise Http404("Edição online desligada neste ambiente.")


def _documento_e_usuario(request, documento_id):
    """Resolve documento + usuário a partir do token WOPI."""
    _exige_flag()
    token = request.GET.get('access_token', '')
    usuario_id = wopi.validar_token(token, documento_id)
    if usuario_id is None:
        logger.warning("wopi: token invalido para documento_id=%s", documento_id)
        return None, None
    documento = DocumentoGerado.objects.filter(pk=documento_id).first()
    if documento is None:
        return None, None
    usuario = User.objects.filter(pk=usuario_id).first()
    return documento, usuario


def _pode_editar(usuario, documento) -> bool:
    if usuario is None:
        return False
    return usuario.is_staff or usuario.is_superuser or documento.usuario_id == usuario.id


@csrf_exempt
@require_http_methods(['GET'])
def check_file_info(request, documento_id):
    """CheckFileInfo — o Collabora chama primeiro para saber o que vai abrir."""
    documento, usuario = _documento_e_usuario(request, documento_id)
    if documento is None or usuario is None:
        return JsonResponse({'erro': 'token invalido'}, status=401)

    try:
        tamanho = documento.arquivo_final.size
    except (ValueError, OSError):
        return JsonResponse({'erro': 'arquivo ausente'}, status=404)

    nome = (documento.arquivo_final.name or 'documento.docx').rsplit('/', 1)[-1]
    pode_escrever = _pode_editar(usuario, documento)

    return JsonResponse({
        'BaseFileName': nome,
        'Size': tamanho,
        'OwnerId': str(documento.usuario_id),
        'UserId': str(usuario.id),
        'UserFriendlyName': usuario.get_full_name() or usuario.username,
        # Version precisa mudar quando o conteúdo muda, senão o editor serve
        # uma versão em cache depois de salvar.
        'Version': documento.data_geracao.isoformat(),
        'UserCanWrite': pode_escrever,
        'UserCanNotWriteRelative': True,   # sem "salvar como"
        'SupportsUpdate': pode_escrever,
        'SupportsLocks': False,            # PoC: um editor por vez
        # Origem da página que embute o iframe — NÃO dá para usar
        # request.build_absolute_uri: este request vem do Collabora, que vê o
        # Django por um endereço interno (web:8000), não pelo do navegador.
        'PostMessageOrigin': settings.COLLABORA_HOST_ORIGIN.rstrip('/'),
    })


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def contents(request, documento_id):
    """GetFile (GET) e PutFile (POST) — no WOPI é a mesma URL."""
    if request.method == 'POST':
        return _put_file(request, documento_id)
    return _get_file(request, documento_id)


def _get_file(request, documento_id):
    """GetFile — devolve os bytes do .docx para o editor."""
    documento, usuario = _documento_e_usuario(request, documento_id)
    if documento is None or usuario is None:
        return HttpResponse(status=401)

    try:
        documento.arquivo_final.open('rb')
        conteudo = documento.arquivo_final.read()
    except (ValueError, OSError):
        return HttpResponse(status=404)
    finally:
        documento.arquivo_final.close()

    return HttpResponse(conteudo, content_type=CONTENT_TYPE_DOCX)


def _put_file(request, documento_id):
    """PutFile — grava o .docx editado por cima do arquivo do documento."""
    documento, usuario = _documento_e_usuario(request, documento_id)
    if documento is None or usuario is None:
        return HttpResponse(status=401)

    if not _pode_editar(usuario, documento):
        raise PermissionDenied("Sem permissão de escrita neste documento.")

    conteudo = request.body
    if not conteudo:
        return HttpResponse(status=400)

    nome = (documento.arquivo_final.name or 'documento.docx').rsplit('/', 1)[-1]
    documento.arquivo_final.save(nome, ContentFile(conteudo), save=True)

    logger.info(
        "wopi: documento_id=%s salvo por usuario_id=%s (%s bytes)",
        documento_id, usuario.id, len(conteudo),
    )

    # O Collabora usa este header para saber que a versão avançou.
    resposta = JsonResponse({'LastModifiedTime': timezone.now().isoformat()})
    resposta['X-WOPI-ItemVersion'] = timezone.now().isoformat()
    return resposta


@login_required
def editar_documento(request, documento_id):
    """Tela que embute o editor do Collabora num iframe."""
    _exige_flag()
    documento = get_object_or_404(
        DocumentoGerado.objects.select_related('template'), pk=documento_id
    )

    if not _pode_editar(request.user, documento):
        raise PermissionDenied("Você só pode editar documentos que você gerou.")

    erro = ''
    url_editor = ''
    try:
        url_editor = wopi.montar_url_editor(documento.id, request.user.id)
    except wopi.CollaboraIndisponivel as exc:
        erro = str(exc)
        logger.warning("editar_documento: %s", exc)

    return render(request, 'docgen/editar_documento.html', {
        'documento': documento,
        'url_editor': url_editor,
        'erro': erro,
    })
