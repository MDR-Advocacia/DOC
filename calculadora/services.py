import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone
from pypdf import PdfReader


TWOPLACES = Decimal('0.01')
FOURPLACES = Decimal('0.0001')


@dataclass
class ExtractionMetadata:
    provider: str
    model: str
    warning: str = ''


def _quantize(value):
    return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _serialize_decimal(value):
    if value in (None, ''):
        return ''
    return format(Decimal(value), 'f')


def _serialize_percentage(value):
    if value in (None, ''):
        return ''
    return format(Decimal(value).quantize(FOURPLACES, rounding=ROUND_HALF_UP), 'f')


def _normalize_decimal(value):
    if value in (None, ''):
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    text = re.sub(r'[^0-9,\.\-]', '', text).strip('.,')
    if ',' in text and '.' in text:
        if text.rfind(',') > text.rfind('.'):
            text = text.replace('.', '').replace(',', '.')
        else:
            text = text.replace(',', '')
    elif ',' in text:
        text = text.replace('.', '').replace(',', '.')
    return Decimal(text)


def _serialize_date(value):
    if not value:
        return ''
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def _extract_json_block(raw_text):
    text = raw_text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?', '', text).strip()
        text = re.sub(r'```$', '', text).strip()
    return json.loads(text)


def extract_text_from_pdf(uploaded_file):
    if not uploaded_file:
        return ''

    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(0)

    try:
        reader = PdfReader(uploaded_file)
    except Exception as exc:
        raise RuntimeError('Nao foi possivel abrir o PDF enviado.') from exc

    if reader.is_encrypted:
        try:
            reader.decrypt('')
        except Exception as exc:
            raise RuntimeError('O PDF esta protegido por senha e nao pode ser processado automaticamente.') from exc

    pages = []
    for page in reader.pages:
        page_text = page.extract_text() or ''
        normalized_lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        if normalized_lines:
            pages.append('\n'.join(normalized_lines))

    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(0)

    extracted_text = '\n\n'.join(pages).strip()
    if not extracted_text:
        raise RuntimeError(
            'Nao foi possivel extrair texto do PDF. Se o arquivo for escaneado sem OCR, sera preciso converter antes.'
        )
    return extracted_text


def _currency_candidates(text):
    matches = re.findall(r'R\$\s*([\d\.\,]*\d)', text, flags=re.IGNORECASE)
    values = []
    for match in matches:
        try:
            values.append(_normalize_decimal(match))
        except Exception:
            continue
    return values


def _first_date_match(pattern, text):
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return _parse_date(match.group(1))


def _heuristic_extract(text):
    principal = ''
    valores = _currency_candidates(text)
    if valores:
        principal = _serialize_decimal(max(valores))

    honorarios_match = re.search(r'honor[aá]rios?(?:\s+advocat[íi]cios)?[^%\d]{0,20}(\d{1,2}(?:[.,]\d+)?)\s*%', text, flags=re.IGNORECASE)
    multa_match = re.search(r'multa[^%\d]{0,20}(\d{1,2}(?:[.,]\d+)?)\s*%', text, flags=re.IGNORECASE)
    juros_match = re.search(r'juros[^%\d]{0,20}(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:ao mes|a\.m\.|mensais)', text, flags=re.IGNORECASE)
    correcao_pct_match = re.search(r'corre[cç][aã]o[^%\d]{0,20}(\d{1,2}(?:[.,]\d+)?)\s*%', text, flags=re.IGNORECASE)

    indice = ''
    for candidate in ('INPC', 'IPCA-E', 'IPCA', 'IGP-M', 'SELIC', 'TR'):
        if candidate.lower() in text.lower():
            indice = candidate
            break

    data_correcao = _first_date_match(r'corre[cç][aã]o.*?(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', text)
    data_juros = _first_date_match(r'juros.*?(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', text)

    parametros = {
        'valor_principal': principal,
        'correcao_percentual': _serialize_percentage(_normalize_decimal(correcao_pct_match.group(1))) if correcao_pct_match else '',
        'indice_correcao': indice,
        'data_termo_inicial_correcao': _serialize_date(data_correcao),
        'juros_mensais_percentual': _serialize_percentage(_normalize_decimal(juros_match.group(1))) if juros_match else '1.0000',
        'data_termo_inicial_juros': _serialize_date(data_juros),
        'data_base_calculo': timezone.localdate().isoformat(),
        'honorarios_percentual': _serialize_percentage(_normalize_decimal(honorarios_match.group(1))) if honorarios_match else '',
        'multa_percentual': _serialize_percentage(_normalize_decimal(multa_match.group(1))) if multa_match else '',
        'outros_acrescimos': '',
        'descontos': '',
        'observacoes_calculo': '',
    }

    itens = []
    if principal:
        itens.append('Valor principal identificado no texto da sentenca.')
    if indice:
        itens.append(f'Indice de correcao mencionado: {indice}.')
    if honorarios_match:
        itens.append('Percentual de honorarios identificado.')
    if juros_match:
        itens.append('Percentual de juros moratorios identificado.')
    if multa_match:
        itens.append('Percentual de multa identificado.')

    pendentes = []
    if not parametros['valor_principal']:
        pendentes.append('Confirmar o valor principal da condenacao.')
    if not parametros['correcao_percentual']:
        pendentes.append('Informar a correcao monetaria acumulada a aplicar.')
    if not parametros['data_termo_inicial_juros']:
        pendentes.append('Informar o termo inicial dos juros, caso a sentenca fixe essa data.')

    resumo = 'Analise heuristica da sentenca para condenacao civel.'
    return {
        'resumo_condenacao': resumo,
        'itens_reconhecidos': itens,
        'campos_pendentes': pendentes,
        'parametros': parametros,
    }


def _build_llm_prompt(text):
    return (
        "Voce e um assistente juridico focado em execucao de sentenca civel. "
        "Leia a sentenca abaixo e devolva apenas JSON valido com as chaves "
        "resumo_condenacao, itens_reconhecidos, campos_pendentes e parametros. "
        "Em parametros, devolva exatamente: valor_principal, correcao_percentual, "
        "indice_correcao, data_termo_inicial_correcao, juros_mensais_percentual, "
        "data_termo_inicial_juros, data_base_calculo, honorarios_percentual, "
        "multa_percentual, outros_acrescimos, descontos, observacoes_calculo. "
        "Datas em YYYY-MM-DD. Numeros sem simbolo de moeda. Se nao souber, use string vazia.\n\n"
        f"SENTENCA:\n{text}"
    )


def _extract_with_openai_compatible(text):
    api_key = (os.environ.get('CALCULO_LLM_API_KEY') or '').strip()
    api_url = (os.environ.get('CALCULO_LLM_API_URL') or 'https://api.openai.com/v1/chat/completions').strip()
    model = (os.environ.get('CALCULO_LLM_MODEL') or 'gpt-4.1-mini').strip()

    if not api_key:
        raise RuntimeError('CALCULO_LLM_API_KEY nao configurada.')

    payload = {
        'model': model,
        'temperature': 0.1,
        'messages': [
            {
                'role': 'system',
                'content': 'Responda somente com JSON valido.',
            },
            {
                'role': 'user',
                'content': _build_llm_prompt(text),
            },
        ],
    }

    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'Falha ao chamar o provedor LLM: {detail or exc.reason}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Falha de rede ao chamar o provedor LLM: {exc.reason}') from exc

    content = body['choices'][0]['message']['content']
    parsed = _extract_json_block(content)
    return parsed, ExtractionMetadata(provider='llm', model=model)


def _merge_parameters(base_params, override_params):
    merged = dict(base_params)
    for key, value in (override_params or {}).items():
        if value not in (None, '', []):
            merged[key] = value
    return merged


def extract_civil_parameters(text):
    heuristic = _heuristic_extract(text)
    base_params = heuristic['parametros']

    try:
        llm_payload, metadata = _extract_with_openai_compatible(text)
        merged = {
            'resumo_condenacao': llm_payload.get('resumo_condenacao') or heuristic['resumo_condenacao'],
            'itens_reconhecidos': llm_payload.get('itens_reconhecidos') or heuristic['itens_reconhecidos'],
            'campos_pendentes': llm_payload.get('campos_pendentes') or heuristic['campos_pendentes'],
            'parametros': _merge_parameters(base_params, llm_payload.get('parametros', {})),
        }
        return merged, metadata
    except Exception as exc:
        metadata = ExtractionMetadata(provider='heuristico', model='regex-fallback', warning=str(exc))
        return heuristic, metadata


def calculation_form_initial(calculo):
    payload = dict(calculo.parametros_extraidos or {})
    payload = payload.get('parametros', payload)
    if calculo.parametros_confirmados:
        payload.update(calculo.parametros_confirmados)
    payload.setdefault('data_base_calculo', timezone.localdate())
    return payload


def calculate_civil_condemnation(cleaned_data):
    valor_principal = _normalize_decimal(cleaned_data.get('valor_principal'))
    correcao_percentual = _normalize_decimal(cleaned_data.get('correcao_percentual') or 0)
    juros_mensais_percentual = _normalize_decimal(cleaned_data.get('juros_mensais_percentual') or 0)
    honorarios_percentual = _normalize_decimal(cleaned_data.get('honorarios_percentual') or 0)
    multa_percentual = _normalize_decimal(cleaned_data.get('multa_percentual') or 0)
    outros_acrescimos = _normalize_decimal(cleaned_data.get('outros_acrescimos') or 0)
    descontos = _normalize_decimal(cleaned_data.get('descontos') or 0)
    data_base = _parse_date(cleaned_data.get('data_base_calculo')) or timezone.localdate()
    data_juros = _parse_date(cleaned_data.get('data_termo_inicial_juros'))

    valor_correcao = _quantize(valor_principal * correcao_percentual / Decimal('100'))
    principal_corrigido = _quantize(valor_principal + valor_correcao)

    dias_juros = 0
    meses_juros = Decimal('0')
    if data_juros and data_base >= data_juros:
        dias_juros = (data_base - data_juros).days
        meses_juros = (Decimal(dias_juros) / Decimal('30')).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

    valor_juros = _quantize(principal_corrigido * juros_mensais_percentual / Decimal('100') * meses_juros)
    subtotal = _quantize(principal_corrigido + valor_juros + outros_acrescimos - descontos)
    base_honorarios = subtotal if subtotal > 0 else Decimal('0')
    valor_honorarios = _quantize(base_honorarios * honorarios_percentual / Decimal('100'))
    valor_multa = _quantize(base_honorarios * multa_percentual / Decimal('100'))
    total_geral = _quantize(subtotal + valor_honorarios + valor_multa)

    memoria = [
        f"Valor principal: R$ {valor_principal:.2f}",
        f"Correcao monetaria aplicada: {correcao_percentual:.4f}% = R$ {valor_correcao:.2f}",
        f"Principal corrigido: R$ {principal_corrigido:.2f}",
        f"Juros moratorios: {juros_mensais_percentual:.4f}% ao mes por {meses_juros:.4f} meses ({dias_juros} dias) = R$ {valor_juros:.2f}",
        f"Outros acrescimos: R$ {outros_acrescimos:.2f}",
        f"Descontos: R$ {descontos:.2f}",
        f"Subtotal da condenacao: R$ {subtotal:.2f}",
        f"Honorarios: {honorarios_percentual:.4f}% = R$ {valor_honorarios:.2f}",
        f"Multa: {multa_percentual:.4f}% = R$ {valor_multa:.2f}",
        f"Total geral: R$ {total_geral:.2f}",
    ]

    if cleaned_data.get('observacoes_calculo'):
        memoria.append(f"Observacoes: {cleaned_data['observacoes_calculo']}")

    resultado = {
        'valor_principal': _serialize_decimal(valor_principal),
        'valor_correcao': _serialize_decimal(valor_correcao),
        'principal_corrigido': _serialize_decimal(principal_corrigido),
        'dias_juros': dias_juros,
        'meses_juros': format(meses_juros, 'f'),
        'valor_juros': _serialize_decimal(valor_juros),
        'subtotal': _serialize_decimal(subtotal),
        'valor_honorarios': _serialize_decimal(valor_honorarios),
        'valor_multa': _serialize_decimal(valor_multa),
        'total_geral': _serialize_decimal(total_geral),
        'memoria_linhas': memoria,
        'data_base_calculo': _serialize_date(data_base),
    }
    return resultado, "\n".join(memoria)
