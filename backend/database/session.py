"""
Engine, sessão e inicialização do banco SQLite.

Ajustes de PRAGMA aplicados a cada conexão:
  * ``foreign_keys=ON``  – o SQLite ignora chaves estrangeiras por padrão;
  * ``journal_mode=WAL`` – leitura concorrente com escrita (essencial para o
    monitor de sistema e o streaming de chat rodando ao mesmo tempo);
  * ``synchronous=NORMAL`` – equilíbrio entre durabilidade e desempenho;
  * ``busy_timeout``     – evita "database is locked" sob carga.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .base import Base

logger = logging.getLogger(__name__)

# ``check_same_thread=False`` é necessário porque o FastAPI executa rotas
# síncronas em um pool de threads.
engine: Engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


@event.listens_for(engine, "connect")
def _configurar_pragmas(dbapi_connection, _connection_record) -> None:
    """Aplica os PRAGMAs de integridade e desempenho em cada nova conexão."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        # ~64 MB de cache de páginas (valor negativo = kibibytes).
        cursor.execute("PRAGMA cache_size=-64000")
    finally:
        cursor.close()


def get_db() -> Iterator[Session]:
    """Dependência do FastAPI: fornece uma sessão por requisição."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def sessao() -> Iterator[Session]:
    """
    Sessão para uso fora do ciclo de requisição (tarefas de fundo, CLI).

    Faz commit ao sair sem erro e rollback em caso de exceção.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def criar_tabelas() -> None:
    """Cria todas as tabelas que ainda não existem."""
    # O import garante que todos os modelos estejam registrados no metadata.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Esquema do banco verificado/criado em %s", settings.database_url)


def apagar_tabelas() -> None:
    """Remove todas as tabelas (uso restrito a testes e reinstalação)."""
    from . import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
