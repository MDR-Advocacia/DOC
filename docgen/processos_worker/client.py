import json
import mimetypes
import uuid
from pathlib import Path
from urllib import error, request


class ProcessosWorkerClient:
    def __init__(self, base_url, token, timeout=60):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.timeout = timeout

    def _headers(self, extra_headers=None):
        headers = {
            'Authorization': f'Bearer {self.token}',
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _json_request(self, method, path, payload=None):
        body = None
        headers = self._headers()
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        req = request.Request(
            f'{self.base_url}{path}',
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode('utf-8')
                if not raw:
                    return None
                return json.loads(raw)
        except error.HTTPError as exc:
            if exc.code == 204:
                return None
            detail = exc.read().decode('utf-8', errors='ignore')
            raise RuntimeError(f'Erro HTTP {exc.code} em {path}: {detail}') from exc

    def claim(self, worker_id):
        return self._json_request(
            'POST',
            '/api/v1/processos/worker/claim/',
            {'worker_id': worker_id},
        )

    def heartbeat(self, execucao_id, mensagem=''):
        return self._json_request(
            'POST',
            f'/api/v1/processos/worker/{execucao_id}/heartbeat/',
            {'mensagem': mensagem},
        )

    def fail(self, execucao_id, status, mensagem, tribunal_url=''):
        return self._json_request(
            'POST',
            f'/api/v1/processos/worker/{execucao_id}/fail/',
            {
                'status': status,
                'mensagem': mensagem,
                'tribunal_url': tribunal_url,
            },
        )

    def complete(self, execucao_id, file_path, checksum, mensagem, tribunal_url=''):
        boundary = uuid.uuid4().hex
        file_path = Path(file_path)
        content_type = mimetypes.guess_type(file_path.name)[0] or 'application/pdf'

        parts = []
        campos = {
            'checksum': checksum,
            'mensagem': mensagem,
            'tribunal_url': tribunal_url,
        }

        for key, value in campos.items():
            parts.extend(
                [
                    f'--{boundary}'.encode('utf-8'),
                    f'Content-Disposition: form-data; name="{key}"'.encode('utf-8'),
                    b'',
                    str(value or '').encode('utf-8'),
                ]
            )

        parts.extend(
            [
                f'--{boundary}'.encode('utf-8'),
                (
                    f'Content-Disposition: form-data; name="arquivo"; '
                    f'filename="{file_path.name}"'
                ).encode('utf-8'),
                f'Content-Type: {content_type}'.encode('utf-8'),
                b'',
                file_path.read_bytes(),
            ]
        )
        parts.append(f'--{boundary}--'.encode('utf-8'))

        body = b'\r\n'.join(parts)
        headers = self._headers(
            {
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            }
        )
        req = request.Request(
            f'{self.base_url}/api/v1/processos/worker/{execucao_id}/complete/',
            data=body,
            headers=headers,
            method='POST',
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode('utf-8')
                return json.loads(raw) if raw else None
        except error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')
            raise RuntimeError(f'Erro HTTP {exc.code} ao concluir execucao: {detail}') from exc
