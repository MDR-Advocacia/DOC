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

    Cobre dois padrões comuns:

    1. ``endereco_ eletronico`` (underscore + espaço + palavra) — split
       residual do Word, quase sempre acidental.
    2. ``{% if executado 2 %}`` / ``{% if avalista N %}`` — dentro de
       ``{% if ... %}`` ou ``{% elif ... %}``, quando o conteúdo entre
       a keyword e ``%}`` é apenas identifiers/números separados por
       espaço (sem operadores Jinja como ``==``, ``and``, ``is``, ``|``),
       junta tudo com underscore. Resolve nomes de variáveis que foram
       digitados com espaço onde deveria ter ``_``.

    Loop até estabilizar pra cobrir casos com múltiplos splits.
    """
    # Padrão 1 — underscore residual
    pattern_underscore = re.compile(r'(_)\s+([A-Za-z_À-ɏ0-9])')

    # Padrão 2 — `{% if X Y %}` onde X e Y são identifiers/números puros.
    # Não casa quando há operador Jinja (==, !=, <, >, |, .) ou keyword
    # de expressão (`is`, `in`, `and`, `or`, `not`).
    pattern_if = re.compile(
        r'(\{%\s*(?:el)?if\s+)'                        # abre {% if ou {% elif
        r'([A-Za-z_À-ɏ][A-Za-z0-9_À-ɏ]*'               # primeiro identifier
        r'(?:\s+[A-Za-z0-9_À-ɏ]+)+)'                   # +um ou mais blocos
        r'(\s*%\})'                                     # fecha %}
    )

    def _join_if(m):
        partes = re.split(r'\s+', m.group(2).strip())
        # Se algum bloco contém keyword Jinja, abortamos e devolvemos como veio.
        keywords = {'is', 'in', 'and', 'or', 'not', 'if', 'else', 'true', 'false', 'none'}
        if any(p.lower() in keywords for p in partes):
            return m.group(0)
        return m.group(1) + '_'.join(partes) + m.group(3)

    while True:
        novo = pattern_underscore.sub(r'\1\2', tag_text)
        novo = pattern_if.sub(_join_if, novo)
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


def validar_template_docx(docx_bytes: bytes) -> tuple[bool, str, list[str]]:
    """Tenta parsear o DOCX como template Jinja/docxtpl.

    Retorna ``(is_valid, mensagem_amigavel, sugestoes)``:
    - ``is_valid``: True se docxtpl consegue parsear sem erro.
    - ``mensagem_amigavel``: mensagem clara em PT-BR explicando o erro
      (quando inválido), ou ``""`` quando válido.
    - ``sugestoes``: lista de tags suspeitas que o usuário deve revisar
      no Word — máximo 10 itens.

    Não joga exceção: erros de parse são convertidos em mensagem.
    """
    import io as _io
    from docxtpl import DocxTemplate
    from jinja2.exceptions import TemplateSyntaxError

    try:
        tpl = DocxTemplate(_io.BytesIO(docx_bytes))
        tpl.get_undeclared_template_variables()
    except TemplateSyntaxError as exc:
        msg = _traduzir_erro_jinja(str(exc.message))
        sugestoes = _listar_tags_suspeitas(docx_bytes)
        return False, msg, sugestoes
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"Não foi possível abrir o documento: {exc}", []

    return True, "", []


# Heurísticas de mensagem amigável a partir do erro cru do Jinja.
_TRADUCOES_ERRO = [
    (
        re.compile(r"expected token 'end of (?:print|statement) block', got '(\w+)'", re.I),
        lambda m: (
            "Há uma tag do template que tem um espaço em branco onde deveria "
            f"ter `_` — perto da palavra ou número `{m.group(1)}`. "
            "Exemplo: troque `{{ endereco eletronico }}` por "
            "`{{ endereco_eletronico }}`, ou `{% if executado 2 %}` por "
            "`{% if executado_2 %}`."
        ),
    ),
    (
        re.compile(r"unexpected end of template", re.I),
        lambda m: (
            "Uma tag `{% if ... %}` ou `{% for ... %}` está aberta mas não "
            "foi fechada com `{% endif %}` / `{% endfor %}` em algum lugar "
            "do documento."
        ),
    ),
    (
        re.compile(r"Encountered unknown tag '(\w+)'", re.I),
        lambda m: (
            f"Tag desconhecida `{{% {m.group(1)} %}}`. Verifique se não está "
            "digitada errada (ex: `endif` virou `endiv` no Word)."
        ),
    ),
]


def _traduzir_erro_jinja(msg_cru: str) -> str:
    """Converte o erro técnico do Jinja em mensagem em PT-BR mais útil."""
    for pattern, builder in _TRADUCOES_ERRO:
        m = pattern.search(msg_cru)
        if m:
            return builder(m) + f"\n\n(Erro técnico: {msg_cru})"
    return f"O Word parece ter quebrado uma tag do template. Erro técnico: {msg_cru}"


def _listar_tags_suspeitas(docx_bytes: bytes) -> list[str]:
    """Varre o texto e devolve tags Jinja que casam com padrões suspeitos."""
    import io as _io
    from docx import Document

    try:
        doc = Document(_io.BytesIO(docx_bytes))
    except Exception:
        return []

    SUSPEITO = re.compile(
        # Tag tem 2+ palavras separadas só por espaço (sem operador, sem ponto)
        r'\{%\s*(?:if|elif)\s+[A-Za-z_][\w]*\s+[A-Za-z_0-9][\w]*'
        r'|'
        # Identifier + espaço + número/identifier sem operador, dentro de {{ }}
        r'\{\{\s*[A-Za-z_][\w]*\s+[A-Za-z_0-9][\w]*\s*\}\}'
    )

    achados: list[str] = []
    paragrafos: list[str] = []
    for p in doc.paragraphs:
        if p.text:
            paragrafos.append(p.text)
    for t in doc.tables:
        for linha in t.rows:
            for c in linha.cells:
                for p in c.paragraphs:
                    if p.text:
                        paragrafos.append(p.text)

    for texto in paragrafos:
        for m in re.finditer(r'\{[%{][^}]{0,300}[%}]\}', texto):
            tag = m.group()
            if SUSPEITO.search(tag) and tag not in achados:
                achados.append(tag)
                if len(achados) >= 10:
                    return achados
    return achados


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
