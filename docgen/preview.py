"""Conversão DOCX → PDF para a pré-visualização fiel.

Por que PDF: navegador não renderiza .docx. Para mostrar a peça exatamente
como vai sair — paginação, margens, fontes, cabeçalho e rodapé — é preciso
converter para um formato que o browser desenhe. O PDF aqui é só o formato
de *exibição*; o arquivo entregue ao usuário continua sendo .docx.

Usa LibreOffice headless. O LibreOffice trava um perfil por vez, então cada
processo tem o seu (``-env:UserInstallation`` com o PID). Worker do gunicorn é
síncrono — atende um request por vez —, logo não há concorrência dentro do
mesmo processo e o perfil pode ser reaproveitado entre conversões.

Medido em container (4 CPUs): perfil frio custa ~1,4s de startup contra ~0,4s
quente. Criar perfil novo a cada chamada dobrava o tempo de uma peça leve.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Em produção o binário vem do pacote libreoffice-writer (ver Dockerfile).
SOFFICE_BIN = os.environ.get('SOFFICE_BIN', 'soffice')
TIMEOUT_CONVERSAO = int(os.environ.get('PREVIEW_TIMEOUT', '90'))


class LibreOfficeIndisponivel(RuntimeError):
    """LibreOffice não está instalado ou não respondeu."""


def libreoffice_disponivel() -> bool:
    return shutil.which(SOFFICE_BIN) is not None


def _perfil_do_processo() -> Path:
    """Perfil do LibreOffice dedicado a este processo, reaproveitado entre
    conversões para não pagar o startup frio toda vez."""
    perfil = Path(tempfile.gettempdir()) / f'lo_profile_{os.getpid()}'
    perfil.mkdir(parents=True, exist_ok=True)
    return perfil


def chave_cache(template, dados, arquivos=None) -> str:
    """Identidade do preview: mesmo modelo + mesmos dados = mesmo PDF.

    Chaveia pelos *dados de entrada*, não pelo .docx renderizado: o
    python-docx grava o timestamp atual em cada entrada do ZIP, então dois
    renders dos mesmos dados produzem bytes diferentes e o hash do arquivo
    nunca repetiria. Chavear pela entrada também evita renderizar de novo
    quando já existe PDF pronto.
    """
    partes = [str(template.id), template.arquivo_template.name]

    for chave in sorted(dados):
        if chave == 'csrfmiddlewaretoken':
            continue
        for valor in sorted(dados.getlist(chave)) if hasattr(dados, 'getlist') else [dados[chave]]:
            partes.append(f"{chave}={valor}")

    for chave in sorted(arquivos or {}):
        arquivo = (arquivos.getlist(chave) if hasattr(arquivos, 'getlist') else [arquivos[chave]])
        for item in arquivo:
            partes.append(f"{chave}#{getattr(item, 'name', '')}:{getattr(item, 'size', 0)}")

    digest = hashlib.sha256('\x1f'.join(partes).encode('utf-8')).hexdigest()[:32]
    return f"preview:{template.id}:{digest}"


def docx_para_pdf(docx_bytes: bytes) -> bytes:
    """Converte DOCX em PDF via LibreOffice headless.

    Levanta LibreOfficeIndisponivel se o binário não existir, estourar o
    timeout ou não produzir saída.
    """
    if not libreoffice_disponivel():
        raise LibreOfficeIndisponivel(
            f"Binário '{SOFFICE_BIN}' não encontrado no PATH."
        )

    perfil = _perfil_do_processo()

    with tempfile.TemporaryDirectory(prefix='preview_') as tmp:
        tmpdir = Path(tmp)
        entrada = tmpdir / 'peca.docx'
        entrada.write_bytes(docx_bytes)

        comando = [
            SOFFICE_BIN,
            f'-env:UserInstallation=file:///{perfil.as_posix().lstrip("/")}',
            '--headless',
            '--norestore',
            '--nolockcheck',
            '--nodefault',
            '--nofirststartwizard',
            '--convert-to', 'pdf:writer_pdf_Export',
            '--outdir', str(tmpdir),
            str(entrada),
        ]

        try:
            resultado = subprocess.run(
                comando,
                capture_output=True,
                timeout=TIMEOUT_CONVERSAO,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LibreOfficeIndisponivel(
                f"A conversão passou de {TIMEOUT_CONVERSAO}s e foi interrompida."
            ) from exc

        saida = tmpdir / 'peca.pdf'
        if not saida.exists():
            logger.error(
                "libreoffice falhou: rc=%s stdout=%r stderr=%r",
                resultado.returncode,
                resultado.stdout[-800:],
                resultado.stderr[-800:],
            )
            raise LibreOfficeIndisponivel(
                "O LibreOffice não gerou o PDF. Veja os logs do container."
            )

        return saida.read_bytes()
