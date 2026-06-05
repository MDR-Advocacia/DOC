"""Normalização de tags Jinja em templates DOCX.

Problema que isso resolve: Word fragmenta palavras com acento/cedilha em runs
XML separados (insere `<w:proofErr/>` no meio) — o pré-processamento do
docxtpl às vezes perde caracteres no merge, gerando erros tipo
`expected token 'end of print statement', got 'eletrônico'`.

Solução: ao subir um template, reescrevemos as tags Jinja com nomes em ASCII
puro (sem acentos, sem cedilha). Texto literal do parágrafo NÃO é alterado.

Apenas parágrafos que contêm tags Jinja com caractere não-ASCII são
re-consolidados (perdem formatação rich local). Parágrafos com tags ASCII
puras ou sem tag Jinja são preservados intactos.
"""

from __future__ import annotations

import io
import re
import unicodedata
from typing import Iterable

from docx import Document
from docx.text.paragraph import Paragraph


JINJA_TAG_PATTERN = re.compile(r'\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}')
# Identifier: letra ou _ (com possíveis acentos), seguido de letras/dígitos/_
IDENTIFIER_PATTERN = re.compile(r'[A-Za-z_À-ɏ][A-Za-z0-9_À-ɏ]*')


def _ascii_normalize(s: str) -> str:
    """Remove diacríticos (acentos, til, cedilha) mantendo letras base."""
    nfd = unicodedata.normalize('NFD', s)
    sem_diac = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    # cedilha em NFD vira c + combining cedilla → após remover diacritic vira "c"
    # Mas alguns chars não decompõem (ex: ß, æ) — esses ficam, sem prejuízo.
    return sem_diac


def _normalize_identifier(match: re.Match) -> str:
    return _ascii_normalize(match.group(0))


def _merge_split_identifiers(tag_text: str) -> str:
    """Junta identifiers acidentalmente partidos por espaço dentro de uma tag.

    Padrão alvo: `endereco_ eletronico` (underscore + espaço + palavra) — quase
    sempre um split acidental (Word inserindo correção, digitação errada).
    Loop até estabilizar pra cobrir casos com múltiplos splits.
    """
    pattern = re.compile(r'(_)\s+([A-Za-z_À-ɏ])')
    while True:
        novo = pattern.sub(r'\1\2', tag_text)
        if novo == tag_text:
            return tag_text
        tag_text = novo


def _normalize_tag(match: re.Match) -> str:
    """Recebe uma tag Jinja `{{ ... }}` ou `{% ... %}` e normaliza:
    1. Junta identifiers partidos por espaço residual (foo_ bar → foo_bar).
    2. Remove acentos/cedilha dos identifiers.

    Não toca em strings literais entre aspas — embora improvável dentro de
    tags Jinja num template típico de peça jurídica."""
    full = match.group(0)
    full = _merge_split_identifiers(full)
    return IDENTIFIER_PATTERN.sub(_normalize_identifier, full)


def _coletar_renames(texto_antes: str, texto_depois: str) -> dict[str, str]:
    """Compara as tags Jinja antes/depois e retorna mapa {antigo: novo}."""
    renames: dict[str, str] = {}
    tags_antes = JINJA_TAG_PATTERN.findall(texto_antes)
    tags_depois = JINJA_TAG_PATTERN.findall(texto_depois)
    for ta, td in zip(tags_antes, tags_depois):
        ids_antes = IDENTIFIER_PATTERN.findall(ta)
        ids_depois = IDENTIFIER_PATTERN.findall(td)
        for ia, idp in zip(ids_antes, ids_depois):
            if ia != idp:
                renames[ia] = idp
    return renames


def _processar_paragrafo(p: Paragraph, renames_acc: dict[str, str]) -> None:
    """Se o parágrafo tem tag Jinja com identificador não-ASCII, normaliza.

    Reescreve o texto consolidado no primeiro run e limpa os outros — perde
    formatação rich local, mas só nesse parágrafo específico.
    """
    texto_orig = p.text
    if not texto_orig or ('{{' not in texto_orig and '{%' not in texto_orig):
        return

    texto_novo = JINJA_TAG_PATTERN.sub(_normalize_tag, texto_orig)
    if texto_novo == texto_orig:
        return  # tags já ASCII, nada a fazer

    renames_acc.update(_coletar_renames(texto_orig, texto_novo))

    if p.runs:
        p.runs[0].text = texto_novo
        for run in p.runs[1:]:
            run.text = ''


def _iterar_paragrafos(doc) -> Iterable[Paragraph]:
    yield from doc.paragraphs
    for tabela in doc.tables:
        for linha in tabela.rows:
            for celula in linha.cells:
                yield from celula.paragraphs
    for section in doc.sections:
        yield from section.header.paragraphs
        yield from section.footer.paragraphs


def normalize_jinja_tags_in_docx(docx_bytes: bytes) -> tuple[bytes, dict[str, str]]:
    """Normaliza nomes de tags Jinja no DOCX, removendo acentos/cedilha.

    Returns:
        (docx_bytes_modificado, renames) — renames é {nome_antigo: nome_novo}
        com apenas os identifiers efetivamente alterados. Se nada precisou
        ser normalizado, renames fica vazio e os bytes voltam praticamente
        idênticos (re-salvos via python-docx — bytes podem diferir mas o
        conteúdo lógico é o mesmo).
    """
    doc = Document(io.BytesIO(docx_bytes))
    renames: dict[str, str] = {}

    for p in _iterar_paragrafos(doc):
        _processar_paragrafo(p, renames)

    if not renames:
        # nada normalizado — devolve bytes originais sem re-salvar
        return docx_bytes, {}

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), renames


def apply_renames_to_configuracao(
    configuracao_campos: list[dict] | None,
    renames: dict[str, str],
) -> list[dict]:
    """Aplica os renames à lista configuracao_campos do Template.

    Atualiza `tag` e qualquer referência em `dependencia`.
    """
    if not configuracao_campos or not renames:
        return configuracao_campos or []
    nova = []
    for campo in configuracao_campos:
        novo = dict(campo)
        if novo.get('tag') in renames:
            novo['tag'] = renames[novo['tag']]
        if novo.get('dependencia') in renames:
            novo['dependencia'] = renames[novo['dependencia']]
        nova.append(novo)
    return nova
