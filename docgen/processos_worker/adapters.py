import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..processos_constants import TRIBUNAIS_ESTADUAIS


class AdapterConfigurationError(RuntimeError):
    pass


class ProcessNotFound(RuntimeError):
    pass


class InitialPetitionNotFound(RuntimeError):
    pass


@dataclass
class CapturedDocument:
    file_path: Path
    tribunal_url: str
    document_name: str


@dataclass
class TribunalAutomationConfig:
    tribunal_codigo: str
    tribunal_nome: str
    portal_url: str
    whom_system_name: str
    search_input_selector: str
    search_submit_selector: str
    document_row_selector: str
    document_name_selector: str
    document_download_selector: str
    process_not_found_text: str
    download_timeout_ms: int
    navigation_timeout_ms: int
    source_label: str = 'principal'

    @classmethod
    def from_env(cls, tribunal_codigo, tribunal_nome, prefix=None, source_label='principal'):
        prefix = prefix or f"PROCESSOS_TRIBUNAL_{tribunal_codigo.replace('.', '_')}"
        portal_url = (
            os.environ.get(f'{prefix}_URL')
            or os.environ.get('PROCESSOS_TRIBUNAL_DEFAULT_URL', '')
        ).strip()

        return cls(
            tribunal_codigo=tribunal_codigo,
            tribunal_nome=tribunal_nome,
            portal_url=portal_url,
            whom_system_name=(
                os.environ.get(f'{prefix}_WHOM_SYSTEM')
                or os.environ.get('PROCESSOS_TRIBUNAL_DEFAULT_WHOM_SYSTEM', '')
            ).strip(),
            search_input_selector=(
                os.environ.get(f'{prefix}_SEARCH_INPUT')
                or os.environ.get('PROCESSOS_TRIBUNAL_DEFAULT_SEARCH_INPUT', '')
            ).strip(),
            search_submit_selector=(
                os.environ.get(f'{prefix}_SEARCH_SUBMIT')
                or os.environ.get('PROCESSOS_TRIBUNAL_DEFAULT_SEARCH_SUBMIT', '')
            ).strip(),
            document_row_selector=(
                os.environ.get(f'{prefix}_DOCUMENT_ROW')
                or os.environ.get('PROCESSOS_TRIBUNAL_DEFAULT_DOCUMENT_ROW', '')
            ).strip(),
            document_name_selector=(
                os.environ.get(f'{prefix}_DOCUMENT_NAME')
                or os.environ.get('PROCESSOS_TRIBUNAL_DEFAULT_DOCUMENT_NAME', '')
            ).strip(),
            document_download_selector=(
                os.environ.get(f'{prefix}_DOCUMENT_DOWNLOAD')
                or os.environ.get('PROCESSOS_TRIBUNAL_DEFAULT_DOCUMENT_DOWNLOAD', '')
            ).strip(),
            process_not_found_text=(
                os.environ.get(f'{prefix}_PROCESS_NOT_FOUND_TEXT')
                or os.environ.get('PROCESSOS_TRIBUNAL_DEFAULT_PROCESS_NOT_FOUND_TEXT', '')
            ).strip(),
            download_timeout_ms=int(os.environ.get('PROCESSOS_WORKER_DOWNLOAD_TIMEOUT_MS') or 90000),
            navigation_timeout_ms=int(os.environ.get('PROCESSOS_WORKER_NAVIGATION_TIMEOUT_MS') or 60000),
            source_label=source_label,
        )


def _normalize_text(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    value = value.encode('ascii', 'ignore').decode('ascii')
    value = value.strip().lower()
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def match_initial_petition_name(document_name):
    normalized = _normalize_text(document_name)
    if not normalized:
        return False

    negative_tokens = {
        'contestacao',
        'sentenca',
        'acordao',
        'embargos',
        'aditamento',
        'emenda',
        'recurso',
        'contrarrazoes',
        'impugnacao',
    }
    if any(token in normalized for token in negative_tokens):
        return False

    if normalized in {'peticao inicial', 'inicial'}:
        return True
    if normalized.startswith('peticao inicial '):
        return True
    if normalized.startswith('inicial '):
        return True
    return False


def resolve_extension_id(extension_path):
    extension_path = Path(str(extension_path or '')).expanduser()
    if not str(extension_path):
        return ''

    configs_path = extension_path / 'configs.json'
    if not configs_path.exists():
        return ''

    try:
        payload = json.loads(configs_path.read_text(encoding='utf-8'))
    except (OSError, TypeError, ValueError):
        return ''

    return str(payload.get('id') or '').strip()


def _has_any_candidate_value(prefix):
    suffixes = (
        'URL',
        'WHOM_SYSTEM',
        'SEARCH_INPUT',
        'SEARCH_SUBMIT',
        'DOCUMENT_ROW',
        'DOCUMENT_NAME',
        'DOCUMENT_DOWNLOAD',
        'PROCESS_NOT_FOUND_TEXT',
    )
    return any((os.environ.get(f'{prefix}_{suffix}') or '').strip() for suffix in suffixes)


def load_tribunal_configs(tribunal_codigo, tribunal_nome):
    base_prefix = f"PROCESSOS_TRIBUNAL_{tribunal_codigo.replace('.', '_')}"
    configs = [
        TribunalAutomationConfig.from_env(
            tribunal_codigo=tribunal_codigo,
            tribunal_nome=tribunal_nome,
            prefix=base_prefix,
            source_label='principal',
        )
    ]

    alt_index = 1
    while True:
        alt_prefix = f'{base_prefix}_ALT_{alt_index}'
        if not _has_any_candidate_value(alt_prefix):
            break
        configs.append(
            TribunalAutomationConfig.from_env(
                tribunal_codigo=tribunal_codigo,
                tribunal_nome=tribunal_nome,
                prefix=alt_prefix,
                source_label=f'alternativo {alt_index}',
            )
        )
        alt_index += 1

    return configs


class GenericWhomTribunalAdapter:
    def __init__(self, config):
        if isinstance(config, list):
            self.configs = config
        else:
            self.configs = [config]

    def _validate_configuration(self, config):
        if not config.portal_url and not config.whom_system_name:
            raise AdapterConfigurationError(
                f"Nem URL nem WHOM_SYSTEM foram configurados para o tribunal {config.tribunal_codigo} ({config.source_label})."
            )
        if not config.search_input_selector:
            raise AdapterConfigurationError(
                f"SEARCH_INPUT nao configurado para o tribunal {config.tribunal_codigo} ({config.source_label})."
            )
        if not config.document_row_selector:
            raise AdapterConfigurationError(
                f"DOCUMENT_ROW nao configurado para o tribunal {config.tribunal_codigo} ({config.source_label})."
            )

    def _open_via_whom(self, config, context, page, extension_path):
        extension_id = resolve_extension_id(extension_path)
        if not extension_id:
            raise AdapterConfigurationError(
                'Nao foi possivel identificar o ID da extensao Whom no caminho configurado.'
            )

        page.goto(f'chrome-extension://{extension_id}/index.html', wait_until='domcontentloaded')

        system_input = page.get_by_placeholder(re.compile(r'busque.*sistema', re.I))
        system_input.click()
        system_input.fill(config.whom_system_name)
        page.wait_for_timeout(800)

        matching_option = page.get_by_text(config.whom_system_name, exact=True)
        if matching_option.count():
            matching_option.first.click()

        page.get_by_role('button', name=re.compile(r'acessar', re.I)).click()

        waited_ms = 0
        while waited_ms < config.navigation_timeout_ms:
            for candidate in context.pages:
                if candidate.url and candidate.url != 'about:blank' and not candidate.url.startswith('chrome-extension://'):
                    candidate.wait_for_load_state('domcontentloaded')
                    return candidate
            if page.url and page.url != 'about:blank' and not page.url.startswith('chrome-extension://'):
                page.wait_for_load_state('domcontentloaded')
                return page
            page.wait_for_timeout(500)
            waited_ms += 500

        raise AdapterConfigurationError(
            f"A Whom nao abriu o sistema '{config.whom_system_name}' a tempo."
        )

    def _open_target_page(self, config, context, page, extension_path):
        if config.whom_system_name:
            return self._open_via_whom(config, context, page, extension_path)
        page.goto(config.portal_url, wait_until='domcontentloaded')
        return page

    def _capture_with_config(
        self,
        config,
        numero_cnj,
        browser_profile_dir,
        download_dir,
        headless=False,
        extension_path='',
    ):
        self._validate_configuration(config)

        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        download_dir = Path(download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)

        browser_args = []
        if extension_path:
            browser_args.extend(
                [
                    f"--disable-extensions-except={extension_path}",
                    f"--load-extension={extension_path}",
                ]
            )

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(browser_profile_dir),
                headless=headless,
                accept_downloads=True,
                args=browser_args,
            )
            page = context.new_page()
            page.set_default_timeout(config.navigation_timeout_ms)

            try:
                page = self._open_target_page(config, context, page, extension_path)
                page.locator(config.search_input_selector).fill(numero_cnj)

                if config.search_submit_selector:
                    page.locator(config.search_submit_selector).click()
                else:
                    page.keyboard.press('Enter')

                if config.process_not_found_text:
                    page.wait_for_timeout(1500)
                    if config.process_not_found_text.lower() in page.content().lower():
                        raise ProcessNotFound(
                            f"Processo {numero_cnj} nao encontrado no sistema {config.source_label}."
                        )

                rows = page.locator(config.document_row_selector)
                rows.first.wait_for(state='visible', timeout=config.navigation_timeout_ms)

                matching_row = None
                matching_name = ''
                for index in range(rows.count()):
                    row = rows.nth(index)
                    if config.document_name_selector:
                        document_name = row.locator(config.document_name_selector).inner_text().strip()
                    else:
                        document_name = row.inner_text().strip()
                    if match_initial_petition_name(document_name):
                        matching_row = row
                        matching_name = document_name
                        break

                if matching_row is None:
                    raise InitialPetitionNotFound(
                        f"Nao foi encontrada peticao inicial para o processo {numero_cnj}."
                    )

                with page.expect_download(timeout=config.download_timeout_ms) as download_info:
                    if config.document_download_selector:
                        matching_row.locator(config.document_download_selector).click()
                    else:
                        matching_row.click()

                download = download_info.value
                suggested_name = download.suggested_filename or f'{numero_cnj}.pdf'
                destino = download_dir / suggested_name
                download.save_as(str(destino))
                return CapturedDocument(
                    file_path=destino,
                    tribunal_url=page.url,
                    document_name=matching_name,
                )
            except PlaywrightTimeoutError as exc:
                raise AdapterConfigurationError(
                    f"Timeout ao automatizar o tribunal {config.tribunal_codigo} ({config.source_label}): {exc}"
                ) from exc
            finally:
                context.close()

    def capture_initial_petition(
        self,
        numero_cnj,
        browser_profile_dir,
        download_dir,
        headless=False,
        extension_path='',
    ):
        process_not_found_messages = []
        configuration_errors = []

        for config in self.configs:
            try:
                return self._capture_with_config(
                    config=config,
                    numero_cnj=numero_cnj,
                    browser_profile_dir=browser_profile_dir,
                    download_dir=download_dir,
                    headless=headless,
                    extension_path=extension_path,
                )
            except ProcessNotFound as exc:
                process_not_found_messages.append(str(exc))
                continue
            except AdapterConfigurationError as exc:
                configuration_errors.append(str(exc))
                continue

        if process_not_found_messages:
            raise ProcessNotFound(' | '.join(process_not_found_messages))
        if configuration_errors:
            raise AdapterConfigurationError(' | '.join(configuration_errors))
        raise AdapterConfigurationError(
            f"Nenhuma configuracao valida foi encontrada para o tribunal {self.configs[0].tribunal_codigo}."
        )


def get_adapter_for_tribunal(tribunal_codigo):
    tribunal_nome = TRIBUNAIS_ESTADUAIS.get(tribunal_codigo)
    if not tribunal_nome:
        raise AdapterConfigurationError(f"Tribunal {tribunal_codigo} nao mapeado.")
    return GenericWhomTribunalAdapter(load_tribunal_configs(tribunal_codigo, tribunal_nome))
