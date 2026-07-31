"""Host WOPI para edição online do .docx pelo Collabora Online (CODE).

Como as peças se encaixam:

    navegador ──(iframe)──> Collabora  http://localhost:9980
                                │
                                └──(WOPI)──> Django  http://web:8000/wopi/...

O navegador nunca fala WOPI. Quem chama estes endpoints é o *container* do
Collabora, para baixar o arquivo, e depois para gravar o que foi editado.
Por isso aqui não há sessão nem CSRF: a autenticação é um token assinado,
de vida curta, embutido na URL que abrimos no iframe.

Endpoints implementados (o mínimo para editar e salvar):
    GET  /wopi/files/<id>            CheckFileInfo — metadados do arquivo
    GET  /wopi/files/<id>/contents   GetFile       — baixa o .docx
    POST /wopi/files/<id>/contents   PutFile       — grava o .docx editado

Locks (Lock/Unlock/RefreshLock) não estão implementados; declaramos
SupportsLocks=false. Serve para um editor por vez, que é o caso da PoC.
Edição simultânea de verdade exige implementar o ciclo de lock.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit
from xml.etree import ElementTree

from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)

SALT = 'docgen.wopi.edicao'
_CACHE_DISCOVERY = 'wopi:discovery:urlsrc:docx'


class CollaboraIndisponivel(RuntimeError):
    """Collabora fora do ar ou sem ação de edição para .docx."""


# ---------------------------------------------------------------------------
# Token de acesso
# ---------------------------------------------------------------------------

def gerar_token(documento_id: int, usuario_id: int) -> str:
    """Token assinado que autoriza editar UM documento por UM usuário."""
    return signing.dumps(
        {'doc': documento_id, 'user': usuario_id},
        salt=SALT,
    )


def validar_token(token: str, documento_id: int) -> int | None:
    """Devolve o usuario_id se o token for válido para este documento.

    Retorna None se estiver expirado, adulterado, ou tiver sido emitido para
    outro documento — sem isso um token válido de um documento abriria
    qualquer outro.
    """
    if not token:
        return None
    try:
        dados = signing.loads(token, salt=SALT, max_age=settings.COLLABORA_TOKEN_TTL)
    except signing.BadSignature:
        return None
    if dados.get('doc') != documento_id:
        return None
    return dados.get('user')


# ---------------------------------------------------------------------------
# Descoberta do editor
# ---------------------------------------------------------------------------

def _reescrever_para_o_navegador(urlsrc: str) -> str:
    """Troca a origem do urlsrc pela que o navegador consegue alcançar.

    O Collabora monta o urlsrc com o endereço pelo qual FOI consultado. Como
    quem consulta é o Django, ele volta como ``http://collabora:9980/...`` —
    nome de serviço que só existe dentro da rede do compose. Se isso fosse
    direto para o iframe, o navegador não carregaria nada.
    """
    origem_navegador = settings.COLLABORA_SERVER_URL.rstrip('/')
    partes = urlsplit(urlsrc)
    if not partes.scheme:
        return urlsrc
    caminho = urlsrc.split(f"{partes.scheme}://{partes.netloc}", 1)[-1]
    return f"{origem_navegador}{caminho}"


def urlsrc_para_docx(timeout: int = 10) -> str:
    """Descobre no Collabora a URL do editor de .docx.

    O caminho mudou entre versões (loleaflet.html → cool.html), então em vez
    de fixar, lemos /hosting/discovery e procuramos a ação de edição do
    formato. O resultado fica em cache: é estático enquanto o container não
    troca de versão.
    """
    from django.core.cache import cache

    cacheado = cache.get(_CACHE_DISCOVERY)
    if cacheado:
        return cacheado

    url = f"{settings.COLLABORA_INTERNAL_URL.rstrip('/')}/hosting/discovery"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resposta:
            corpo = resposta.read()
    except (urllib.error.URLError, OSError) as exc:
        raise CollaboraIndisponivel(
            f"Não consegui falar com o Collabora em {url}: {exc}"
        ) from exc

    try:
        raiz = ElementTree.fromstring(corpo)
    except ElementTree.ParseError as exc:
        raise CollaboraIndisponivel(
            f"O /hosting/discovery do Collabora não devolveu XML válido: {exc}"
        ) from exc

    # <net-zone><app name="..."><action name="edit" ext="docx" urlsrc="..."/>
    for acao in raiz.iter('action'):
        if acao.get('ext') == 'docx' and acao.get('name') in ('edit', 'view'):
            urlsrc = acao.get('urlsrc')
            if urlsrc:
                urlsrc = _reescrever_para_o_navegador(urlsrc)
                cache.set(_CACHE_DISCOVERY, urlsrc, 3600)
                return urlsrc

    raise CollaboraIndisponivel(
        "O Collabora respondeu, mas não anunciou nenhuma ação para .docx."
    )


def montar_url_editor(documento_id: int, usuario_id: int) -> str:
    """URL completa do iframe: editor + de onde buscar o arquivo + token."""
    urlsrc = urlsrc_para_docx()

    wopi_src = (
        f"{settings.COLLABORA_WOPI_HOST.rstrip('/')}/wopi/files/{documento_id}"
    )
    separador = '&' if urlsrc.endswith('?') or '?' in urlsrc else '?'
    if urlsrc.endswith('?'):
        separador = ''

    parametros = urlencode({
        'WOPISrc': wopi_src,
        'access_token': gerar_token(documento_id, usuario_id),
        'lang': 'pt-BR',
    }, quote_via=quote)

    return f"{urlsrc}{separador}{parametros}"
