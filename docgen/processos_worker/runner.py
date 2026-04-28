import hashlib
import os
import tempfile
import time
from pathlib import Path

from .adapters import (
    AdapterConfigurationError,
    InitialPetitionNotFound,
    ProcessNotFound,
    get_adapter_for_tribunal,
)
from .client import ProcessosWorkerClient


class ProcessosWorker:
    def __init__(
        self,
        client,
        worker_id,
        poll_seconds,
        browser_profile_dir,
        extension_path='',
        headless=False,
    ):
        self.client = client
        self.worker_id = worker_id
        self.poll_seconds = poll_seconds
        self.browser_profile_dir = Path(browser_profile_dir)
        self.extension_path = extension_path
        self.headless = headless

    @classmethod
    def from_env(cls):
        base_url = (os.environ.get('PROCESSOS_WORKER_API_BASE_URL') or 'http://web:8000').strip()
        token = (os.environ.get('PROCESSOS_WORKER_TOKEN') or '').strip()
        if not token:
            raise RuntimeError('PROCESSOS_WORKER_TOKEN nao configurado.')

        return cls(
            client=ProcessosWorkerClient(base_url=base_url, token=token),
            worker_id=(os.environ.get('PROCESSOS_WORKER_ID') or 'processos-worker').strip(),
            poll_seconds=int(os.environ.get('PROCESSOS_WORKER_POLL_SECONDS') or 15),
            browser_profile_dir=(
                os.environ.get('PROCESSOS_WORKER_BROWSER_PROFILE') or '/app/.processos-browser-profile'
            ).strip(),
            extension_path=(os.environ.get('PROCESSOS_WORKER_EXTENSION_PATH') or '').strip(),
            headless=(os.environ.get('PROCESSOS_WORKER_HEADLESS') or '').strip().lower() in {'1', 'true', 'yes', 'on'},
        )

    def run_forever(self):
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        while True:
            payload = self.client.claim(self.worker_id)
            if not payload:
                time.sleep(self.poll_seconds)
                continue
            self._process_payload(payload)

    def _process_payload(self, payload):
        execucao_id = payload['id']
        processo = payload['processo']
        numero_cnj = processo['numero_cnj']
        tribunal_codigo = processo['tribunal_codigo']

        self.client.heartbeat(execucao_id, f"Captura iniciada para o processo {numero_cnj}.")

        try:
            adapter = get_adapter_for_tribunal(tribunal_codigo)
            with tempfile.TemporaryDirectory(prefix='processos-worker-') as tmp_dir:
                result = adapter.capture_initial_petition(
                    numero_cnj=numero_cnj,
                    browser_profile_dir=self.browser_profile_dir,
                    download_dir=tmp_dir,
                    headless=self.headless,
                    extension_path=self.extension_path,
                )
                checksum = hashlib.sha256(result.file_path.read_bytes()).hexdigest()
                self.client.complete(
                    execucao_id=execucao_id,
                    file_path=result.file_path,
                    checksum=checksum,
                    mensagem=f"Documento '{result.document_name}' capturado com sucesso.",
                    tribunal_url=result.tribunal_url,
                )
        except ProcessNotFound as exc:
            self.client.fail(
                execucao_id,
                status='PROCESSO_NAO_ENCONTRADO',
                mensagem=str(exc),
            )
        except InitialPetitionNotFound as exc:
            self.client.fail(
                execucao_id,
                status='PETICAO_NAO_LOCALIZADA',
                mensagem=str(exc),
            )
        except AdapterConfigurationError as exc:
            self.client.fail(
                execucao_id,
                status='FALHA_TECNICA',
                mensagem=str(exc),
            )
        except Exception as exc:  # pragma: no cover - runtime fallback
            self.client.fail(
                execucao_id,
                status='FALHA_TECNICA',
                mensagem=f'Falha tecnica inesperada: {exc}',
            )
