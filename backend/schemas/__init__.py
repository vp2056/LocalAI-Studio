"""Esquemas Pydantic de entrada e saída da API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Base(BaseModel):
    """Base com leitura direta de objetos ORM."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


# ===========================================================================
# Autenticação
# ===========================================================================
class LoginIn(Base):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegistroIn(Base):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[\w.\-]+$")
    password: str = Field(min_length=8, max_length=256)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=160)


class TrocaSenhaIn(Base):
    senha_atual: str
    senha_nova: str = Field(min_length=8, max_length=256)


class UsuarioOut(Base):
    id: int
    username: str
    email: str | None = None
    full_name: str | None = None
    avatar: str | None = None
    role: str
    is_active: bool
    preferences: dict[str, Any] = {}
    created_at: datetime
    last_login: datetime | None = None


class TokenOut(Base):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UsuarioOut


# ===========================================================================
# Modelos de IA
# ===========================================================================
class ModeloOut(Base):
    id: int
    name: str
    path: str
    format: str
    backend: str
    kind: str
    size_bytes: int
    quantization: str | None = None
    parameters: str | None = None
    architecture: str | None = None
    context_length: int
    description: str | None = None
    is_available: bool
    is_default: bool
    usage_count: int
    meta: dict[str, Any] = {}
    last_used_at: datetime | None = None


class ImportarModeloIn(Base):
    caminho: str = Field(description="Caminho absoluto do arquivo ou pasta do modelo")
    nome: str | None = None
    copiar: bool = Field(
        default=True, description="Copiar para models/ em vez de referenciar no lugar"
    )


class BaixarModeloIn(Base):
    url: str = Field(max_length=2048)
    nome_arquivo: str | None = None


class AtualizarModeloIn(Base):
    description: str | None = None
    context_length: int | None = Field(default=None, ge=256, le=1_048_576)
    is_default: bool | None = None
    default_params: dict[str, Any] | None = None
    kind: str | None = None


class DownloadOut(Base):
    id: int
    url: str
    filename: str
    status: str
    total_bytes: int
    downloaded_bytes: int
    speed_bps: float
    progress: float
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


# ===========================================================================
# Geração e chat
# ===========================================================================
class ParametrosIn(Base):
    max_tokens: int | None = Field(default=None, ge=1, le=131_072)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0, le=1000)
    repeat_penalty: float | None = Field(default=None, ge=0.5, le=3.0)
    seed: int | None = None
    stop: list[str] | None = None


class ChatIn(Base):
    mensagem: str = Field(min_length=1, max_length=200_000)
    conversation_id: int | None = None
    modelo: str | None = None
    agent_id: int | None = None
    usar_rag: bool = True
    stream: bool = False
    params: ParametrosIn | None = None

    @field_validator("mensagem")
    @classmethod
    def _nao_vazia(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("A mensagem não pode ser vazia.")
        return valor


class GenerateIn(Base):
    """Geração sem conversa: prompt puro, sem persistência."""

    prompt: str = Field(min_length=1, max_length=200_000)
    modelo: str | None = None
    system: str | None = None
    params: ParametrosIn | None = None


class FonteOut(Base):
    index: int
    document_id: int | None = None
    title: str | None = None
    score: float
    page: int | None = None
    excerpt: str


class ChatOut(Base):
    content: str
    model: str
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    tokens: int
    duration_ms: int
    tokens_per_second: float
    sources: list[FonteOut] = []
    error: str | None = None


class GenerateOut(Base):
    content: str
    model: str
    tokens: int
    duration_ms: int
    tokens_per_second: float


# ===========================================================================
# Conversas e mensagens
# ===========================================================================
class ConversaIn(Base):
    title: str | None = Field(default=None, max_length=300)
    model_name: str | None = None
    agent_id: int | None = None
    system_prompt: str | None = None
    rag_collections: list[str] | None = None
    params: dict[str, Any] | None = None


class ConversaUpdateIn(ConversaIn):
    pinned: bool | None = None
    archived: bool | None = None
    tags: list[str] | None = None


class MensagemOut(Base):
    id: int
    conversation_id: int
    role: str
    content: str
    model_name: str | None = None
    tokens: int
    duration_ms: int
    tokens_per_second: float
    meta: dict[str, Any] = {}
    edited: bool
    error: str | None = None
    created_at: datetime


class ConversaOut(Base):
    id: int
    title: str
    model_name: str | None = None
    agent_id: int | None = None
    system_prompt: str | None = None
    rag_collections: list[str] = []
    params: dict[str, Any] = {}
    pinned: bool
    archived: bool
    tags: list[str] = []
    message_count: int
    total_tokens: int
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None


class ConversaDetalheOut(ConversaOut):
    messages: list[MensagemOut] = []


class EditarMensagemIn(Base):
    content: str = Field(min_length=1, max_length=200_000)
    regenerar: bool = True


# ===========================================================================
# Agentes
# ===========================================================================
class AgenteIn(Base):
    name: str = Field(min_length=1, max_length=120)
    avatar: str | None = Field(default=None, max_length=512)
    description: str | None = None
    system_prompt: str = ""
    model_name: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    top_k: int = Field(default=40, ge=0, le=1000)
    max_tokens: int = Field(default=1024, ge=1, le=131_072)
    tools: list[str] = []
    rag_collections: list[str] = []
    memory_enabled: bool = True


class AgenteUpdateIn(Base):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    model_name: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0, le=1000)
    max_tokens: int | None = Field(default=None, ge=1, le=131_072)
    tools: list[str] | None = None
    rag_collections: list[str] | None = None
    memory_enabled: bool | None = None
    is_active: bool | None = None


class AgenteOut(Base):
    id: int
    name: str
    avatar: str | None = None
    description: str | None = None
    system_prompt: str
    model_name: str | None = None
    temperature: float
    top_p: float
    top_k: int
    max_tokens: int
    tools: list[str] = []
    memory: list[dict[str, Any]] = []
    memory_enabled: bool
    rag_collections: list[str] = []
    is_active: bool
    usage_count: int
    created_at: datetime


class MemoriaIn(Base):
    fato: str = Field(min_length=1, max_length=2000)


# ===========================================================================
# RAG e documentos
# ===========================================================================
class DocumentoOut(Base):
    id: int
    title: str
    filename: str
    filetype: str
    size_bytes: int
    collection: str
    status: str
    chunk_count: int
    char_count: int
    error: str | None = None
    meta: dict[str, Any] = {}
    created_at: datetime
    indexed_at: datetime | None = None


class BuscaRagIn(Base):
    consulta: str = Field(min_length=1, max_length=10_000)
    k: int = Field(default=5, ge=1, le=50)
    colecoes: list[str] | None = None
    score_minimo: float | None = Field(default=None, ge=-1.0, le=1.0)


class ResultadoRagOut(Base):
    embedding_id: int
    score: float
    content: str
    document_id: int | None = None
    document_title: str | None = None
    collection: str
    meta: dict[str, Any] = {}


class EmbeddingsIn(Base):
    textos: list[str] = Field(min_length=1, max_length=512)


class EmbeddingsOut(Base):
    vetores: list[list[float]]
    modelo: str
    dimensao: int


# ===========================================================================
# Plugins
# ===========================================================================
class PluginOut(Base):
    id: int
    slug: str
    name: str
    version: str
    author: str | None = None
    description: str | None = None
    homepage: str | None = None
    hooks: list[str] = []
    permissions: list[str] = []
    config: dict[str, Any] = {}
    enabled: bool
    installed: bool
    error: str | None = None


# ===========================================================================
# Configurações, favoritos e logs
# ===========================================================================
class ConfiguracaoIn(Base):
    value: Any


class ConfiguracaoOut(Base):
    key: str
    value: Any = None
    category: str
    description: str | None = None


class FavoritoIn(Base):
    target_type: str = Field(
        pattern=r"^(conversation|model|agent|document|message|prompt)$"
    )
    target_id: int
    label: str | None = None
    notes: str | None = None


class FavoritoOut(Base):
    id: int
    target_type: str
    target_id: int
    label: str | None = None
    notes: str | None = None
    created_at: datetime


class LogOut(Base):
    id: int
    level: str
    source: str
    message: str
    context: dict[str, Any] = {}
    created_at: datetime


# ===========================================================================
# Extras
# ===========================================================================
class TTSIn(Base):
    texto: str = Field(min_length=1, max_length=20_000)
    voz: str | None = None


class GerarImagemIn(Base):
    prompt: str = Field(min_length=1, max_length=2000)
    prompt_negativo: str = ""
    modelo: str | None = None
    largura: int = Field(default=512, ge=128, le=2048, multiple_of=8)
    altura: int = Field(default=512, ge=128, le=2048, multiple_of=8)
    passos: int = Field(default=25, ge=1, le=150)
    escala: float = Field(default=7.5, ge=0.0, le=30.0)
    semente: int | None = None


# ===========================================================================
# Utilitários
# ===========================================================================
class PaginaOut(Base):
    """Envelope de resposta paginada."""

    items: list[Any]
    total: int
    page: int
    per_page: int
    pages: int


class MensagemSimples(Base):
    detail: str
