"""
Configuração de logging: console + arquivo rotativo + persistência em banco.

O handler de banco é intencionalmente tolerante a falhas: um problema ao
gravar log jamais pode derrubar a requisição que o originou.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from typing import Any

from ..config import settings

FORMATO = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"

# Níveis abaixo deste não são persistidos no banco (evita inchaço da tabela).
NIVEL_MINIMO_BANCO = logging.WARNING


class BancoHandler(logging.Handler):
    """Persiste registros relevantes na tabela ``logs``."""

    def __init__(self, level: int = NIVEL_MINIMO_BANCO) -> None:
        super().__init__(level)
        self._ativo = False

    def ativar(self) -> None:
        """Liga a persistência (chamado após a criação das tabelas)."""
        self._ativo = True

    def emit(self, record: logging.LogRecord) -> None:
        if not self._ativo:
            return
        try:
            # Import tardio: evita dependência circular com o módulo de banco.
            from ..database.models import Log
            from ..database.session import SessionLocal

            contexto: dict[str, Any] = {}
            if record.exc_info:
                contexto["exception"] = self.format(record)

            db = SessionLocal()
            try:
                db.add(
                    Log(
                        level=record.levelname,
                        source=record.name[:120],
                        message=record.getMessage()[:8000],
                        context=contexto,
                    )
                )
                db.commit()
            finally:
                db.close()
        except Exception:
            # Silencioso por design: logar a falha de log causaria recursão.
            pass


_handler_banco = BancoHandler()


def configurar_logging(nivel: str | None = None) -> None:
    """Instala os handlers no logger raiz (idempotente)."""
    raiz = logging.getLogger()
    if getattr(raiz, "_lais_configurado", False):
        return

    raiz.setLevel(getattr(logging, (nivel or settings.log_level).upper(), logging.INFO))
    formatador = logging.Formatter(FORMATO, datefmt=FORMATO_DATA)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatador)
    raiz.addHandler(console)

    arquivo = logging.handlers.RotatingFileHandler(
        settings.caminho("logs") / "localai_studio.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    arquivo.setFormatter(formatador)
    raiz.addHandler(arquivo)

    erros = logging.handlers.RotatingFileHandler(
        settings.caminho("logs") / "erros.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    erros.setLevel(logging.ERROR)
    erros.setFormatter(formatador)
    raiz.addHandler(erros)

    _handler_banco.setFormatter(formatador)
    raiz.addHandler(_handler_banco)

    # Bibliotecas ruidosas em nível de depuração.
    for ruidoso in ("watchdog", "urllib3", "httpx", "multipart", "PIL"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    raiz._lais_configurado = True  # type: ignore[attr-defined]


def ativar_log_em_banco() -> None:
    """Habilita a gravação de logs no banco (após ``criar_tabelas``)."""
    _handler_banco.ativar()
