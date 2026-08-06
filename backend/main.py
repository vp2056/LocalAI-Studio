"""
Aplicação FastAPI do LocalAI Studio.

Monta middlewares, rotas, WebSocket e o frontend estático, e cuida do ciclo de
vida: inicialização do banco, varredura de modelos/plugins e backup periódico.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import agents, auth, chat, extras, models, plugins, rag, system
from .api.ws import chat_ws
from .config import settings
from .core.exceptions import registrar_tratadores
from .core.logging_config import ativar_log_em_banco, configurar_logging
from .core.middleware import (
    CSRFMiddleware,
    RateLimitMiddleware,
    RequestLogMiddleware,
    SecurityHeadersMiddleware,
)
from .database.init_db import inicializar_banco
from .services.backup.service import servico_backup
from .services.llm.manager import gerenciador
from .services.plugins.manager import gerenciador_plugins

logger = logging.getLogger(__name__)

DESCRICAO = """
API do **LocalAI Studio** — plataforma de IA local, 100% offline.

* **Chat** com modelos locais e streaming em tempo real
* **Modelos** GGUF, safetensors e ONNX gerenciados localmente
* **RAG** sobre PDF, DOCX, TXT, HTML, Markdown, CSV e JSON
* **Agentes** personalizados com memória e ferramentas
* **Plugins** extensíveis com marketplace local
"""


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Inicialização e encerramento ordenados da aplicação."""
    configurar_logging()
    logger.info("Iniciando %s v%s…", settings.app_name, settings.version)

    inicializar_banco()
    ativar_log_em_banco()

    # A varredura toca o disco; sai do event loop para não bloquear o start.
    await asyncio.to_thread(gerenciador.escanear)
    await asyncio.to_thread(gerenciador_plugins.escanear)
    await asyncio.to_thread(gerenciador_plugins.carregar_ativos)
    gerenciador_plugins.executar_gancho("on_startup")

    tarefa_backup = (
        asyncio.create_task(_backup_periodico()) if settings.backup_enabled else None
    )

    logger.info(
        "Pronto em http://%s:%d  (modo: %s)", settings.host, settings.port, settings.mode
    )

    yield

    logger.info("Encerrando…")
    if tarefa_backup:
        tarefa_backup.cancel()
    gerenciador_plugins.executar_gancho("on_shutdown")
    gerenciador.descarregar_todos()
    logger.info("Encerrado.")


async def _backup_periodico() -> None:
    """Cria backups automáticos no intervalo configurado."""
    intervalo = max(1, settings.backup_interval_hours) * 3600
    while True:
        try:
            await asyncio.sleep(intervalo)
            await asyncio.to_thread(servico_backup.criar)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Falha de backup não pode encerrar a tarefa periódica.
            logger.exception("Falha no backup automático.")


app = FastAPI(
    title=settings.app_name,
    description=DESCRICAO,
    version=settings.version,
    lifespan=ciclo_de_vida,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ---------------------------------------------------------------------------
# Middlewares — a ordem importa: o último adicionado é o primeiro a executar.
# ---------------------------------------------------------------------------
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLogMiddleware)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

registrar_tratadores(app)

# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(models.router, prefix="/api")
app.include_router(rag.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(plugins.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(extras.router, prefix="/api")
app.include_router(chat_ws.router)

# ---------------------------------------------------------------------------
# Frontend estático
# ---------------------------------------------------------------------------
PASTA_FRONTEND = settings.caminho("frontend")

if PASTA_FRONTEND.exists():
    app.mount(
        "/static", StaticFiles(directory=PASTA_FRONTEND), name="static"
    )

    @app.get("/", include_in_schema=False)
    async def raiz():
        """Serve a interface web."""
        indice = PASTA_FRONTEND / "index.html"
        if indice.exists():
            return FileResponse(indice)
        return JSONResponse(
            {"detail": "Interface não encontrada. Verifique a pasta frontend/."},
            status_code=404,
        )

    @app.get("/{caminho:path}", include_in_schema=False)
    async def spa(caminho: str):
        """
        Devolve o index para rotas do frontend.

        Requisições a /api/ que chegam aqui são 404 reais — não devem receber
        HTML no lugar de JSON.
        """
        if caminho.startswith(("api/", "ws/", "static/")):
            return JSONResponse({"detail": "Rota não encontrada."}, status_code=404)

        arquivo = PASTA_FRONTEND / caminho
        if arquivo.is_file():
            return FileResponse(arquivo)

        indice = PASTA_FRONTEND / "index.html"
        if indice.exists():
            return FileResponse(indice)
        return JSONResponse({"detail": "Rota não encontrada."}, status_code=404)
