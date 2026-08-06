"""
Download de modelos por URL, com progresso e retomada.

Usado tanto pela interface (URL direta ou de um repositório HuggingFace)
quanto pela importação em lote. O download roda em thread separada e o
progresso é persistido na tabela ``downloads``, de onde a interface o lê.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from ...config import settings
from ...core.exceptions import ArquivoInvalido
from ...database.base import agora
from ...database.models import Download
from ...database.session import sessao

logger = logging.getLogger(__name__)

BLOCO = 1024 * 512  # 512 KB por leitura
INTERVALO_PROGRESSO = 1.0  # segundos entre gravações de progresso no banco


class GerenciadorDownloads:
    """Downloads de modelos em segundo plano."""

    def __init__(self) -> None:
        self._cancelados: set[int] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- início
    def iniciar(self, url: str, *, nome_arquivo: str | None = None) -> Download:
        """Registra e dispara um download; retorna o registro criado."""
        analisado = urlparse(url)
        if analisado.scheme not in ("http", "https"):
            raise ArquivoInvalido("Apenas URLs http(s) são aceitas.")

        nome = nome_arquivo or unquote(Path(analisado.path).name) or "modelo.gguf"
        nome = Path(nome).name  # descarta qualquer componente de diretório

        extensao = Path(nome).suffix.lower()
        if extensao not in settings.allowed_model_ext:
            raise ArquivoInvalido(
                f"Extensão '{extensao}' não permitida. "
                f"Aceitas: {', '.join(settings.allowed_model_ext)}"
            )

        destino = settings.caminho("models") / nome

        with sessao() as db:
            registro = Download(
                url=url,
                filename=nome,
                destination=str(destino),
                status="pending",
            )
            db.add(registro)
            db.flush()
            download_id = registro.id

        thread = threading.Thread(
            target=self._executar,
            args=(download_id, url, destino),
            daemon=True,
            name=f"download-{download_id}",
        )
        thread.start()

        with sessao() as db:
            return db.get(Download, download_id)  # type: ignore[return-value]

    # ----------------------------------------------------------- execução
    def _executar(self, download_id: int, url: str, destino: Path) -> None:
        """Baixa o arquivo, atualizando o progresso periodicamente."""
        parcial = destino.with_suffix(destino.suffix + ".parcial")
        ja_baixado = parcial.stat().st_size if parcial.exists() else 0

        self._atualizar(download_id, status="downloading")

        try:
            cabecalhos = {"Range": f"bytes={ja_baixado}-"} if ja_baixado else {}
            with requests.get(
                url, stream=True, timeout=(15, 120), headers=cabecalhos
            ) as resposta:
                resposta.raise_for_status()

                # 206 = servidor aceitou a retomada; 200 = recomeça do zero.
                retomando = resposta.status_code == 206
                if not retomando:
                    ja_baixado = 0

                total = int(resposta.headers.get("content-length", 0)) + (
                    ja_baixado if retomando else 0
                )
                self._atualizar(download_id, total_bytes=total)

                modo = "ab" if retomando and ja_baixado else "wb"
                baixado = ja_baixado
                inicio = time.monotonic()
                ultimo_relato = 0.0

                with parcial.open(modo) as arquivo:
                    for pedaco in resposta.iter_content(BLOCO):
                        if self._cancelado(download_id):
                            self._atualizar(download_id, status="cancelled")
                            logger.info("Download %d cancelado.", download_id)
                            return

                        arquivo.write(pedaco)
                        baixado += len(pedaco)

                        decorrido = time.monotonic() - inicio
                        if decorrido - ultimo_relato >= INTERVALO_PROGRESSO:
                            velocidade = (baixado - ja_baixado) / max(decorrido, 0.001)
                            self._atualizar(
                                download_id,
                                downloaded_bytes=baixado,
                                speed_bps=velocidade,
                            )
                            ultimo_relato = decorrido

            parcial.replace(destino)
            self._atualizar(
                download_id,
                status="completed",
                downloaded_bytes=destino.stat().st_size,
                finished_at=agora(),
            )
            logger.info("Download concluído: %s", destino.name)

            # Registra o novo modelo imediatamente.
            from .manager import gerenciador

            gerenciador.escanear()

        except Exception as exc:
            logger.exception("Falha no download %d", download_id)
            self._atualizar(
                download_id, status="failed", error=str(exc)[:2000], finished_at=agora()
            )
        finally:
            with self._lock:
                self._cancelados.discard(download_id)

    # -------------------------------------------------------------- apoio
    def cancelar(self, download_id: int) -> bool:
        """Sinaliza o cancelamento; o arquivo parcial é preservado."""
        with self._lock:
            self._cancelados.add(download_id)
        return True

    def _cancelado(self, download_id: int) -> bool:
        with self._lock:
            return download_id in self._cancelados

    def _atualizar(self, download_id: int, **campos) -> None:
        with sessao() as db:
            registro = db.get(Download, download_id)
            if registro:
                for chave, valor in campos.items():
                    setattr(registro, chave, valor)

    def listar(self, limite: int = 50) -> list[Download]:
        with sessao() as db:
            return (
                db.query(Download)
                .order_by(Download.created_at.desc())
                .limit(limite)
                .all()
            )


# Instância única.
gerenciador_downloads = GerenciadorDownloads()
