"""Exceções de domínio e seus tratadores HTTP."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class LocalAIError(Exception):
    """Erro base da aplicação."""

    status_code = 400
    codigo = "erro"

    def __init__(self, mensagem: str, *, detalhes: dict | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.detalhes = detalhes or {}


class ModeloNaoEncontrado(LocalAIError):
    """O modelo solicitado não existe ou não está disponível."""

    status_code = 404
    codigo = "modelo_nao_encontrado"


class ModeloNaoCarregado(LocalAIError):
    """Nenhum modelo carregado para atender a requisição."""

    status_code = 409
    codigo = "modelo_nao_carregado"


class BackendIndisponivel(LocalAIError):
    """Dependência opcional do backend de inferência não está instalada."""

    status_code = 503
    codigo = "backend_indisponivel"


class RecursoNaoEncontrado(LocalAIError):
    """Entidade não encontrada no banco."""

    status_code = 404
    codigo = "nao_encontrado"


class PermissaoNegada(LocalAIError):
    """O usuário não tem permissão para a operação."""

    status_code = 403
    codigo = "permissao_negada"


class ArquivoInvalido(LocalAIError):
    """Upload rejeitado (extensão, tamanho ou conteúdo inválido)."""

    status_code = 422
    codigo = "arquivo_invalido"


class PluginError(LocalAIError):
    """Falha na instalação ou execução de um plugin."""

    status_code = 400
    codigo = "erro_plugin"


def registrar_tratadores(app: FastAPI) -> None:
    """Instala os tratadores de exceção na aplicação."""

    @app.exception_handler(LocalAIError)
    async def _erro_dominio(_: Request, exc: LocalAIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.mensagem, "code": exc.codigo, **exc.detalhes},
        )

    @app.exception_handler(RequestValidationError)
    async def _erro_validacao(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Mensagem legível em vez do dump bruto do Pydantic.
        problemas = [
            {"campo": ".".join(str(p) for p in e["loc"][1:]), "erro": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Dados inválidos na requisição.",
                "code": "validacao",
                "errors": problemas,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _erro_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": f"http_{exc.status_code}"},
        )

    @app.exception_handler(Exception)
    async def _erro_inesperado(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "-")
        logger.exception("[%s] Erro não tratado", request_id)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Erro interno do servidor.",
                "code": "erro_interno",
                "request_id": request_id,
            },
        )
