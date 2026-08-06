"""
Modelos ORM do LocalAI Studio.

Cobre as 14 entidades previstas na especificação:
users, models, agents, messages, conversations, embeddings, documents,
plugins, downloads, settings, logs, sessions, api_keys, favorites.

Convenções:
  * Campos livres/estruturados são guardados como JSON (SQLite suporta nativamente).
  * Exclusões em cascata são declaradas no ORM e reforçadas por PRAGMA no engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


# ===========================================================================
# Usuários, sessões e chaves de API
# ===========================================================================
class User(Base, TimestampMixin):
    """Usuário do sistema."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, default=None)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(160), default=None)
    avatar: Mapped[str | None] = mapped_column(String(512), default=None)
    # Papéis: "admin" (controle total) ou "user" (uso comum).
    role: Mapped[str] = mapped_column(String(32), default="user", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    favorites: Mapped[list["Favorite"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Session(Base, TimestampMixin):
    """Sessão de login ativa (permite revogar tokens individualmente)."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Identificador único do token (claim "jti" do JWT).
    token_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class ApiKey(Base, TimestampMixin):
    """Chave de API para integrações externas (modo servidor)."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    # Guardamos apenas o hash da chave; o valor puro é exibido uma única vez.
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    user: Mapped[User] = relationship(back_populates="api_keys")


# ===========================================================================
# Modelos de IA
# ===========================================================================
class AIModel(Base, TimestampMixin):
    """Metadados de um modelo de IA disponível localmente."""

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    # Caminho absoluto do arquivo ou do diretório do modelo.
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    # Formato: gguf | safetensors | onnx | transformers
    format: Mapped[str] = mapped_column(String(32), index=True)
    # Backend responsável pela execução: llama_cpp | transformers | onnx | echo
    backend: Mapped[str] = mapped_column(String(32), default="llama_cpp", index=True)
    # Finalidade: chat | embedding | vision | image | speech
    kind: Mapped[str] = mapped_column(String(32), default="chat", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    quantization: Mapped[str | None] = mapped_column(String(32), default=None)
    parameters: Mapped[str | None] = mapped_column(String(32), default=None)
    architecture: Mapped[str | None] = mapped_column(String(64), default=None)
    context_length: Mapped[int] = mapped_column(Integer, default=4096)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    license: Mapped[str | None] = mapped_column(String(120), default=None)
    source_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    checksum: Mapped[str | None] = mapped_column(String(128), default=None)
    # Parâmetros padrão de geração específicos deste modelo.
    default_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Metadados técnicos extraídos do arquivo (cabeçalho GGUF, config.json…).
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Download(Base, TimestampMixin):
    """Download de modelo em andamento, concluído ou com falha."""

    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048))
    filename: Mapped[str] = mapped_column(String(512))
    destination: Mapped[str] = mapped_column(String(1024))
    # Situação: pending | downloading | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    speed_bps: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    @property
    def progress(self) -> float:
        """Percentual concluído (0..100)."""
        if self.total_bytes <= 0:
            return 0.0
        return round(self.downloaded_bytes / self.total_bytes * 100, 2)


# ===========================================================================
# Agentes
# ===========================================================================
class Agent(Base, TimestampMixin):
    """Agente personalizado: persona + parâmetros + ferramentas."""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    avatar: Mapped[str | None] = mapped_column(String(512), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    # Modelo padrão do agente (nome registrado em "models").
    model_name: Mapped[str | None] = mapped_column(String(200), default=None)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    top_p: Mapped[float] = mapped_column(Float, default=0.95)
    top_k: Mapped[int] = mapped_column(Integer, default=40)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    # Ferramentas habilitadas, por nome (ver services/agents/tools.py).
    tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Memória permanente do agente: lista de fatos consolidados.
    memory: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Coleções RAG que o agente pode consultar.
    rag_collections: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)


# ===========================================================================
# Conversas e mensagens
# ===========================================================================
class Conversation(Base, TimestampMixin):
    """Conversa (thread) entre usuário e modelo/agente."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None, index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="Nova conversa")
    model_name: Mapped[str | None] = mapped_column(String(200), default=None)
    system_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    # Parâmetros de geração fixados para esta conversa.
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Coleções RAG anexadas à conversa.
    rag_collections: Mapped[list[str]] = mapped_column(JSON, default=list)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    agent: Mapped[Agent | None] = relationship()
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base, TimestampMixin):
    """Mensagem individual dentro de uma conversa."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    # Papel: system | user | assistant | tool
    role: Mapped[str] = mapped_column(String(24), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str | None] = mapped_column(String(200), default=None)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Tempo de geração em milissegundos e tokens por segundo.
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_per_second: Mapped[float] = mapped_column(Float, default=0.0)
    # Trechos RAG usados como contexto, anexos, chamadas de ferramenta etc.
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Marca respostas que foram editadas ou regeneradas pelo usuário.
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    regenerated_from: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# Índice composto: acelera a listagem paginada de mensagens por conversa.
Index("ix_messages_conv_id", Message.conversation_id, Message.id)


# ===========================================================================
# RAG: documentos e embeddings
# ===========================================================================
class Document(Base, TimestampMixin):
    """Documento importado para a base de conhecimento."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    title: Mapped[str] = mapped_column(String(400), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(String(1024))
    # Extensão normalizada: pdf | docx | txt | html | md | csv | json
    filetype: Mapped[str] = mapped_column(String(16), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str | None] = mapped_column(String(128), index=True, default=None)
    collection: Mapped[str] = mapped_column(String(120), default="default", index=True)
    # Situação da indexação: pending | processing | indexed | failed
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str | None] = mapped_column(String(16), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    embeddings: Mapped[list["Embedding"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Embedding(Base, TimestampMixin):
    """
    Trecho (chunk) de documento com seu vetor.

    O vetor fica em ``vector`` como float32 bruto — compacto e rápido de
    reconstruir com ``numpy.frombuffer``. O índice FAISS/Chroma é derivado
    desta tabela, que é sempre a fonte da verdade e permite reconstrução total.
    """

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    collection: Mapped[str] = mapped_column(String(120), default="default", index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    dim: Mapped[int] = mapped_column(Integer, default=384)
    model_name: Mapped[str | None] = mapped_column(String(200), default=None)
    # Posição do trecho no documento original (página, linha, offset…).
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="embeddings")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_embedding_chunk"),
    )


# ===========================================================================
# Plugins
# ===========================================================================
class Plugin(Base, TimestampMixin):
    """Plugin instalado (extensão do sistema)."""

    __tablename__ = "plugins"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    author: Mapped[str | None] = mapped_column(String(160), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    homepage: Mapped[str | None] = mapped_column(String(512), default=None)
    path: Mapped[str] = mapped_column(String(1024))
    # Ganchos declarados no manifesto (ex.: on_message, on_startup).
    hooks: Mapped[list[str]] = mapped_column(JSON, default=list)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    installed: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)


# ===========================================================================
# Configurações, logs e favoritos
# ===========================================================================
class Setting(Base, TimestampMixin):
    """Configuração persistida em banco (sobrepõe o settings.yaml em runtime)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    value: Mapped[Any] = mapped_column(JSON, default=None)
    category: Mapped[str] = mapped_column(String(64), default="geral", index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)


class Log(Base, TimestampMixin):
    """Registro de evento do sistema, consultável pela interface."""

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO", index=True)
    source: Mapped[str] = mapped_column(String(120), default="system", index=True)
    message: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), default=None)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Favorite(Base, TimestampMixin):
    """Item favoritado pelo usuário (conversa, modelo, agente, documento…)."""

    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Tipo do alvo: conversation | model | agent | document | message | prompt
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str | None] = mapped_column(String(300), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    user: Mapped[User] = relationship(back_populates="favorites")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "target_type", "target_id", name="uq_favorite_target"
        ),
    )


__all__ = [
    "User",
    "Session",
    "ApiKey",
    "AIModel",
    "Download",
    "Agent",
    "Conversation",
    "Message",
    "Document",
    "Embedding",
    "Plugin",
    "Setting",
    "Log",
    "Favorite",
]
