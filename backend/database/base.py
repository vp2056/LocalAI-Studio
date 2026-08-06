"""Classe base declarativa e utilitários comuns do ORM."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def agora() -> datetime:
    """Data/hora atual em UTC (sempre com fuso explícito)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos."""


class TimestampMixin:
    """Adiciona colunas de auditoria de criação/atualização."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora, onupdate=agora, server_default=func.now()
    )
