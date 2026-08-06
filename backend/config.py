"""
Configuração central do LocalAI Studio.

Todas as opções podem ser sobrescritas por:
  1. variáveis de ambiente com prefixo ``LAIS_`` (ex.: ``LAIS_PORT=9000``);
  2. arquivo ``config/settings.yaml`` (criado automaticamente na 1ª execução).

A precedência é: variável de ambiente > settings.yaml > padrão do código.
"""

from __future__ import annotations

import os
import secrets
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Empacotado com PyInstaller? Nesse caso os dados graváveis e os recursos
# somente-leitura vivem em lugares diferentes.
CONGELADO = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _raiz_dados() -> Path:
    """
    Onde ficam os diretórios graváveis (banco, modelos, logs, uploads…).

    No executável empacotado é a pasta do binário — o bundle interno é
    temporário/somente-leitura e não pode guardar estado.
    """
    if CONGELADO:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _raiz_recursos() -> Path:
    """Onde ficam os recursos somente-leitura embutidos (frontend)."""
    if CONGELADO:
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


# Raiz do projeto (…/LocalAIStudio) — este arquivo vive em backend/config.py
BASE_DIR = _raiz_dados()

# Diretórios de trabalho previstos na arquitetura do projeto.
DIRS: dict[str, Path] = {
    "database": BASE_DIR / "database",
    "models": BASE_DIR / "models",
    "documents": BASE_DIR / "documents",
    "plugins": BASE_DIR / "plugins",
    "logs": BASE_DIR / "logs",
    "config": BASE_DIR / "config",
    "uploads": BASE_DIR / "uploads",
    "downloads": BASE_DIR / "downloads",
    "temp": BASE_DIR / "temp",
    "backups": BASE_DIR / "backups",
    # O frontend é estático: vem de dentro do bundle quando empacotado.
    "frontend": _raiz_recursos() / "frontend",
}

CONFIG_FILE = DIRS["config"] / "settings.yaml"


def _garantir_diretorios() -> None:
    """Cria toda a árvore de diretórios graváveis, se ainda não existir."""
    for nome, caminho in DIRS.items():
        if nome == "frontend":
            continue  # recurso somente-leitura; pode estar dentro do bundle
        caminho.mkdir(parents=True, exist_ok=True)


def _carregar_yaml() -> dict[str, Any]:
    """Lê ``config/settings.yaml``; devolve dict vazio se não existir/for inválido."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        dados = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except Exception:  # arquivo corrompido não pode derrubar o sistema
        return {}


class Settings(BaseSettings):
    """Configurações da aplicação."""

    model_config = SettingsConfigDict(
        env_prefix="LAIS_",
        env_file=".env",
        extra="ignore",
        # Evita conflito com o namespace protegido "model_" do Pydantic.
        protected_namespaces=(),
    )

    # ---------------------------------------------------------------- geral
    app_name: str = "LocalAI Studio"
    version: str = "1.0.0"
    debug: bool = False
    # Modos suportados: "server" (rede), "desktop" (app local), "portable".
    mode: str = "server"

    # ----------------------------------------------------------- servidor
    host: str = "127.0.0.1"
    port: int = 8080
    # Origens permitidas para CORS. Vazio = mesma origem apenas (recomendado).
    cors_origins: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------ banco
    database_url: str = f"sqlite:///{DIRS['database'] / 'localai_studio.db'}"

    # --------------------------------------------------------- segurança
    # Chave JWT: gerada e persistida em settings.yaml na primeira execução.
    secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 dias
    # Autenticação pode ser dispensada nos modos desktop/portátil de 1 usuário.
    auth_required: bool = True
    csrf_enabled: bool = True
    # Limite global: requisições por janela, por IP.
    rate_limit_requests: int = 240
    rate_limit_window_seconds: int = 60

    # ------------------------------------------------------------- LLM
    # Backend padrão: "llama_cpp" | "transformers" | "onnx" | "echo".
    default_backend: str = "llama_cpp"
    default_model: str | None = None
    context_length: int = 4096
    max_tokens: int = 1024
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    repeat_penalty: float = 1.1
    seed: int = -1  # -1 = aleatório
    n_threads: int = 0  # 0 = detectar automaticamente
    n_gpu_layers: int = 0  # 0 = somente CPU
    # Quantos modelos podem ficar carregados em RAM simultaneamente.
    max_loaded_models: int = 1

    # ------------------------------------------------------------- RAG
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    # Backend vetorial: "faiss" | "chroma" | "numpy" (fallback puro).
    vector_backend: str = "faiss"
    chunk_size: int = 800
    chunk_overlap: int = 120
    rag_top_k: int = 5
    rag_min_score: float = 0.20

    # --------------------------------------------------------- uploads
    max_upload_mb: int = 512
    allowed_document_ext: list[str] = Field(
        default_factory=lambda: [
            ".pdf", ".docx", ".txt", ".html", ".htm", ".md", ".csv", ".json",
        ]
    )
    allowed_model_ext: list[str] = Field(
        default_factory=lambda: [".gguf", ".safetensors", ".onnx", ".bin"]
    )

    # --------------------------------------------------------- backups
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    backup_keep: int = 10

    # ----------------------------------------------------------- logs
    log_level: str = "INFO"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5

    # ---------------------------------------------------------- extras
    ocr_enabled: bool = True
    stt_enabled: bool = True
    tts_enabled: bool = True
    image_generation_enabled: bool = True
    # Sincronização LAN: anuncia/descobre outras instâncias na rede local.
    lan_sync_enabled: bool = False
    lan_sync_port: int = 8765

    # ------------------------------------------------------- utilitários
    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @property
    def dirs(self) -> dict[str, Path]:
        return DIRS

    def caminho(self, chave: str) -> Path:
        """Retorna um diretório de trabalho pelo nome lógico."""
        return DIRS[chave]


def _persistir_chave_secreta(settings: Settings) -> Settings:
    """
    Garante que exista uma ``secret_key`` estável entre reinícios.

    Sem isso, todos os tokens JWT seriam invalidados a cada reinicialização.
    """
    if settings.secret_key:
        return settings

    dados = _carregar_yaml()
    chave = dados.get("secret_key")
    if not chave:
        chave = secrets.token_urlsafe(64)
        dados["secret_key"] = chave
        CONFIG_FILE.write_text(
            yaml.safe_dump(dados, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        # Permissão restrita: o arquivo guarda material criptográfico.
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            pass  # sistemas de arquivo sem suporte a chmod (ex.: FAT32)

    settings.secret_key = chave
    return settings


@lru_cache
def get_settings() -> Settings:
    """Instância única (cacheada) das configurações."""
    _garantir_diretorios()
    # YAML fornece os padrões; variáveis de ambiente ainda têm precedência,
    # pois o BaseSettings as aplica por cima dos valores passados aqui.
    do_yaml = {k: v for k, v in _carregar_yaml().items() if k != "secret_key"}
    # Valores vindos de variáveis de ambiente têm precedência sobre o YAML,
    # então descartamos as chaves do YAML que já foram definidas no ambiente.
    do_yaml = {
        k: v
        for k, v in do_yaml.items()
        if f"{Settings.model_config['env_prefix']}{k}".upper() not in os.environ
    }
    settings = Settings(**do_yaml)
    return _persistir_chave_secreta(settings)


settings = get_settings()
