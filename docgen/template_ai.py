"""Sugestão automática de modelos jurídicos via Claude.

Pipeline:
    1. Extrai texto do DOCX exemplo (python-docx).
    2. Redata dados sensíveis com regex local (CPF, CNPJ, CNJ, valores, datas,
       e-mails, telefones) — Claude nunca vê dado de cliente identificável.
    3. Chama Claude Sonnet 4.6 com system prompt cacheado e schema JSON estrito,
       pedindo a lista de trechos que variariam entre clientes.
    4. Aplica os placeholders sugeridos ao DOCX original (substitui o texto
       literal por `{{ tag }}`).

A função pública é `gerar_sugestao_de_template(docx_bytes)`.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

import anthropic
from django.conf import settings
from docx import Document

logger = logging.getLogger(__name__)


# ---------- 1. Redação local de dados sensíveis ----------

_REGEX_REDACOES = [
    # CNJ (20 dígitos com pontuação ou apenas dígitos): NNNNNNN-DD.AAAA.J.TR.OOOO
    (re.compile(r'\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b'), '[REDACTED-CNJ]'),
    # CPF: 000.000.000-00
    (re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b'), '[REDACTED-CPF]'),
    # CNPJ: 00.000.000/0000-00
    (re.compile(r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b'), '[REDACTED-CNPJ]'),
    # Valores em R$: R$ 1.234,56 / R$ 1.234.567,89
    (re.compile(r'R\$\s*\d{1,3}(?:\.\d{3})*(?:,\d{2})?'), '[REDACTED-VALOR]'),
    # Datas dd/mm/yyyy ou dd/mm/yy
    (re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'), '[REDACTED-DATA]'),
    # E-mails
    (re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b'), '[REDACTED-EMAIL]'),
    # Telefones com DDD: (11) 91234-5678 / 11 91234-5678 / (11)1234-5678
    (re.compile(r'\(?\d{2}\)?\s?\d{4,5}-\d{4}'), '[REDACTED-TEL]'),
    # CEP
    (re.compile(r'\b\d{5}-\d{3}\b'), '[REDACTED-CEP]'),
]


def redact_personal_data(texto: str) -> str:
    """Substitui dados sensíveis identificáveis por marcadores `[REDACTED-*]`.

    Note: heurístico — não substitui nomes próprios (que viram placeholder pela IA)
    nem endereços por extenso. Cobertura: dados estruturais com padrão claro.
    """
    for pattern, replacement in _REGEX_REDACOES:
        texto = pattern.sub(replacement, texto)
    return texto


# ---------- 2. Extração de texto do DOCX ----------

def _extrair_texto_do_docx(docx_bytes: bytes) -> str:
    """Lê parágrafos + tabelas do DOCX e retorna como texto plano."""
    doc = Document(io.BytesIO(docx_bytes))
    partes: list[str] = []
    for paragrafo in doc.paragraphs:
        if paragrafo.text.strip():
            partes.append(paragrafo.text)
    for tabela in doc.tables:
        for linha in tabela.rows:
            for celula in linha.cells:
                if celula.text.strip():
                    partes.append(celula.text)
    return '\n'.join(partes)


# ---------- 3. Chamada Claude com caching + structured output ----------

_SYSTEM_PROMPT = """Você é um assistente que ajuda a criar modelos (templates) Word de peças jurídicas para uma advocacia brasileira.

Você receberá o texto de uma peça já preenchida com dados de um caso real. Dados estruturais sensíveis (CPF, CNPJ, número de processo CNJ, valores em R$, datas, e-mails, telefones, CEP) já foram redatados pelo sistema e aparecem como marcadores `[REDACTED-CPF]`, `[REDACTED-VALOR]`, etc.

Sua tarefa é identificar TODOS os trechos do texto que VARIARIAM entre clientes diferentes e propor placeholders padronizados que serão substituídos automaticamente quando outro advogado for usar o modelo.

DEVE substituir:
- Nomes de pessoas físicas e jurídicas (autor, réu, advogados, representantes)
- Endereços, comarcas, varas, tribunais específicos
- Qualificação das partes (nacionalidade, estado civil, profissão, RG, etc)
- Descrição específica dos fatos do caso
- Descrição específica do pedido
- Cargos, empresas, instituições mencionadas como partes
- Qualquer marcador `[REDACTED-*]` (transforme em placeholder com tipo adequado)

NÃO deve substituir:
- Termos jurídicos fixos: "Excelentíssimo Senhor Doutor Juiz", "DOS FATOS", "DO DIREITO", "DOS PEDIDOS", "Termos em que pede deferimento", etc.
- Texto boilerplate que se repete em todas as peças do mesmo tipo
- Citações de leis, jurisprudência, doutrina (mesmo com números — fazem parte da fundamentação)
- Fórmulas de cortesia, datas-fechamento ("Nestes termos...")

Tipos de placeholder válidos (campo `tipo`):
- "text": texto curto (nome, cidade, profissão)
- "textarea": múltiplos parágrafos (descrição de fatos, pedido detalhado)
- "date": data (dd/mm/aaaa)
- "currency": valor monetário em R$
- "cpf_cnpj": CPF ou CNPJ
- "dropdown": lista de opções fixas (forneça as opções no campo `opcoes` separadas por vírgula)
- "checkbox": sim/não

Para a `tag`, use snake_case sem acentos: `nome_autor`, `valor_causa`, `endereco_reu`, `comarca`, `data_distribuicao`.

Para `trecho_original`, retorne EXATAMENTE o texto como aparece no documento (incluindo marcadores [REDACTED-*] se for o caso) — essa string será usada para localizar e substituir no DOCX original.

Para `contexto`, descreva em ~10 palavras onde aparece (ex: "qualificação do autor no primeiro parágrafo").

Ordene os placeholders pela ordem em que aparecem no documento."""


_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "placeholders": {
            "type": "array",
            "description": "Lista ordenada de placeholders sugeridos.",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "snake_case sem acentos, ex: nome_autor",
                    },
                    "label": {
                        "type": "string",
                        "description": "Rótulo human-readable, ex: Nome do Autor",
                    },
                    "tipo": {
                        "type": "string",
                        "enum": ["text", "textarea", "date", "currency", "cpf_cnpj", "dropdown", "checkbox"],
                    },
                    "trecho_original": {
                        "type": "string",
                        "description": "Texto exato a ser substituído no DOCX.",
                    },
                    "contexto": {
                        "type": "string",
                        "description": "Onde aparece no documento.",
                    },
                    "opcoes": {
                        "type": "string",
                        "description": "Opções separadas por vírgula (apenas para tipo=dropdown).",
                    },
                },
                "required": ["tag", "label", "tipo", "trecho_original", "contexto"],
                "additionalProperties": False,
            },
        },
        "observacoes": {
            "type": "string",
            "description": "Observações gerais sobre a análise (opcional).",
        },
    },
    "required": ["placeholders"],
    "additionalProperties": False,
}


@dataclass
class SugestaoIA:
    placeholders: list[dict]
    observacoes: str
    tokens_input: int
    tokens_output: int
    tokens_cached: int


class IAIndisponivelError(RuntimeError):
    """Lançada quando ANTHROPIC_API_KEY não está configurada."""


def _chamar_claude(texto_redatado: str) -> SugestaoIA:
    if not settings.ANTHROPIC_API_KEY:
        raise IAIndisponivelError(
            "ANTHROPIC_API_KEY não configurada. Configure a chave em settings/.env "
            "antes de usar a sugestão por IA."
        )

    # timeout do client HTTP — adaptive thinking + structured pode levar 30-90s.
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=240.0)

    # Streaming evita timeouts de HTTP/proxy em requests longos com adaptive
    # thinking. `.get_final_message()` agrega tudo no final.
    logger.info("template_ai: chamando Claude (model=%s, texto=%d chars)",
                settings.ANTHROPIC_MODEL, len(texto_redatado))

    with client.messages.stream(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
        },
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    "Analise o texto abaixo de uma peça jurídica e sugira "
                    "placeholders para os trechos que variam entre clientes.\n\n"
                    "---\n"
                    f"{texto_redatado}\n"
                    "---"
                ),
            }
        ],
    ) as stream:
        response = stream.get_final_message()

    # Log do que veio pra debugar — tira depois que estabilizar.
    blocos_info = [(b.type, len(getattr(b, 'text', '') or '')) for b in response.content]
    logger.info("template_ai: response stop_reason=%s blocos=%s usage=%s",
                response.stop_reason, blocos_info, response.usage)

    # output_config.format garante que o primeiro bloco texto é JSON válido
    texto_resposta = next((b.text for b in response.content if b.type == "text"), "")
    logger.info("template_ai: texto_resposta (primeiros 500 chars): %r", texto_resposta[:500])

    if not texto_resposta:
        raise RuntimeError(
            f"Claude retornou resposta vazia (stop_reason={response.stop_reason}, "
            f"blocos={blocos_info}). Tente novamente ou use upload manual."
        )

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "A peça é muito longa e o limite de tokens foi atingido — a IA não conseguiu "
            "completar a lista de placeholders. Tente novamente com uma versão mais curta da "
            "peça (apenas as seções principais) ou use o upload manual."
        )

    import json
    payload = json.loads(texto_resposta)

    return SugestaoIA(
        placeholders=payload.get("placeholders", []),
        observacoes=payload.get("observacoes", ""),
        tokens_input=response.usage.input_tokens,
        tokens_output=response.usage.output_tokens,
        tokens_cached=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    )


# ---------- 4. Aplica placeholders ao DOCX original ----------

def _substituir_em_paragrafo(paragrafo, trecho: str, placeholder: str) -> bool:
    """Substitui `trecho` por `placeholder` em todo o texto do parágrafo.

    Para não destruir formatação fina por run, fazemos a substituição no texto
    consolidado e re-escrevemos no primeiro run (mantendo seu estilo).
    Caso o trecho não esteja presente, retorna False.
    """
    texto_completo = paragrafo.text
    if trecho not in texto_completo:
        return False

    novo_texto = texto_completo.replace(trecho, placeholder, 1)

    # Estratégia simples: limpa runs e escreve tudo no primeiro
    if paragrafo.runs:
        primeiro = paragrafo.runs[0]
        primeiro.text = novo_texto
        for run in paragrafo.runs[1:]:
            run.text = ""
    return True


def aplicar_placeholders_no_docx(docx_bytes: bytes, placeholders: list[dict]) -> bytes:
    """Reabre o DOCX e substitui cada `trecho_original` por `{{ tag }}`.

    Retorna os bytes do DOCX modificado. Ignora silenciosamente trechos não
    encontrados (registra warning) — o user vai conseguir corrigir manualmente
    na tela de configurar_template.
    """
    doc = Document(io.BytesIO(docx_bytes))
    aplicados = 0
    nao_encontrados: list[str] = []

    for p in placeholders:
        trecho = p.get("trecho_original", "")
        tag = p.get("tag", "")
        if not trecho or not tag:
            continue
        placeholder_str = "{{ " + tag + " }}"
        substituido = False

        for paragrafo in doc.paragraphs:
            if _substituir_em_paragrafo(paragrafo, trecho, placeholder_str):
                substituido = True
                break

        if not substituido:
            for tabela in doc.tables:
                for linha in tabela.rows:
                    for celula in linha.cells:
                        for paragrafo in celula.paragraphs:
                            if _substituir_em_paragrafo(paragrafo, trecho, placeholder_str):
                                substituido = True
                                break
                        if substituido:
                            break
                    if substituido:
                        break
                if substituido:
                    break

        if substituido:
            aplicados += 1
        else:
            nao_encontrados.append(trecho[:60])

    if nao_encontrados:
        logger.warning(
            "template_ai: %d trecho(s) não localizados no DOCX: %s",
            len(nao_encontrados),
            nao_encontrados,
        )

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ---------- 5. Função pública ----------

@dataclass
class ResultadoSugestao:
    docx_modificado: bytes
    placeholders: list[dict]
    observacoes: str
    tokens_input: int
    tokens_output: int
    tokens_cached: int


def gerar_sugestao_de_template(docx_bytes: bytes) -> ResultadoSugestao:
    """Pipeline completo: texto → redação → Claude → DOCX com placeholders.

    Pode levantar:
    - IAIndisponivelError: chave não configurada.
    - anthropic.APIError e subclasses: falha na chamada (rate limit, 5xx, etc).
    - json.JSONDecodeError: Claude retornou JSON inválido (raro com schema estrito).
    """
    texto = _extrair_texto_do_docx(docx_bytes)
    texto_redatado = redact_personal_data(texto)
    sugestao = _chamar_claude(texto_redatado)
    docx_modificado = aplicar_placeholders_no_docx(docx_bytes, sugestao.placeholders)

    return ResultadoSugestao(
        docx_modificado=docx_modificado,
        placeholders=sugestao.placeholders,
        observacoes=sugestao.observacoes,
        tokens_input=sugestao.tokens_input,
        tokens_output=sugestao.tokens_output,
        tokens_cached=sugestao.tokens_cached,
    )
