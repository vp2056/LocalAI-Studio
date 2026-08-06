"""
Middlewares transversais: rate limit, CSRF, cabeçalhos de segurança e
registro de requisições.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import settings
from .security import gerar_csrf_token, validar_csrf_token

logger = logging.getLogger(__name__)

# Métodos que alteram estado e, portanto, exigem verificação CSRF.
METODOS_INSEGUROS = {"POST", "PUT", "PATCH", "DELETE"}

# Rotas isentas de CSRF: login/registro ainda não têm cookie de sessão, e
# clientes de API se autenticam por Bearer/API key (imunes a CSRF).
ISENTAS_CSRF = {"/api/auth/login", "/api/auth/register", "/api/auth/csrf"}

NOME_COOKIE_CSRF = "lais_csrf"
NOME_HEADER_CSRF = "X-CSRF-Token"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Limite de requisições por IP em janela deslizante.

    Implementação em memória (deque de timestamps por IP) — adequada a uma
    instância local; um deploy multiprocesso exigiria um repositório externo.
    """

    def __init__(self, app, limite: int | None = None, janela: int | None = None):
        super().__init__(app)
        self.limite = limite or settings.rate_limit_requests
        self.janela = janela or settings.rate_limit_window_seconds
        self._historico: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        # Arquivos estáticos e healthcheck não consomem cota.
        if not request.url.path.startswith("/api/") or request.url.path.endswith(
            "/health"
        ):
            return await call_next(request)

        ip = _ip_cliente(request)
        agora = time.monotonic()
        marcas = self._historico[ip]

        while marcas and agora - marcas[0] > self.janela:
            marcas.popleft()

        if len(marcas) >= self.limite:
            retry = int(self.janela - (agora - marcas[0])) + 1
            logger.warning("Rate limit atingido para %s", ip)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Muitas requisições. Tente novamente em instantes.",
                    "retry_after": retry,
                },
                headers={"Retry-After": str(retry)},
            )

        marcas.append(agora)

        # Poda periódica: impede crescimento indefinido do dicionário.
        if len(self._historico) > 4096:
            for chave in [k for k, v in self._historico.items() if not v]:
                self._historico.pop(chave, None)

        resposta = await call_next(request)
        resposta.headers["X-RateLimit-Limit"] = str(self.limite)
        resposta.headers["X-RateLimit-Remaining"] = str(
            max(0, self.limite - len(marcas))
        )
        return resposta


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Proteção CSRF por double submit cookie.

    Requisições autenticadas por cabeçalho ``Authorization``/``X-API-Key`` são
    dispensadas: não usam cookie ambiente, logo não são forjáveis por um site
    de terceiros.
    """

    async def dispatch(self, request: Request, call_next):
        precisa_validar = (
            settings.csrf_enabled
            and request.method in METODOS_INSEGUROS
            and request.url.path.startswith("/api/")
            and request.url.path not in ISENTAS_CSRF
            and not request.headers.get("authorization")
            and not request.headers.get("x-api-key")
        )

        if precisa_validar:
            enviado = request.headers.get(NOME_HEADER_CSRF)
            do_cookie = request.cookies.get(NOME_COOKIE_CSRF)
            if not enviado or enviado != do_cookie or not validar_csrf_token(enviado):
                logger.warning(
                    "CSRF rejeitado em %s %s", request.method, request.url.path
                )
                return JSONResponse(
                    status_code=403, content={"detail": "Token CSRF inválido ou ausente."}
                )

        resposta = await call_next(request)

        # Emite o cookie CSRF quando ainda não existe.
        if settings.csrf_enabled and NOME_COOKIE_CSRF not in request.cookies:
            resposta.set_cookie(
                NOME_COOKIE_CSRF,
                gerar_csrf_token(),
                httponly=False,  # o front precisa lê-lo para reenviar no header
                samesite="strict",
                secure=request.url.scheme == "https",
                max_age=60 * 60 * 12,
                path="/",
            )
        return resposta


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Cabeçalhos de defesa contra XSS, clickjacking e sniffing de MIME."""

    # CSP restrita: sem CDNs, tudo é servido localmente (requisito offline).
    # 'unsafe-inline' em style-src é necessário para estilos dinâmicos do chat.
    CSP = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "media-src 'self' blob:; "
        "connect-src 'self' ws: wss:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )

    async def dispatch(self, request: Request, call_next):
        resposta: Response = await call_next(request)
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "no-referrer")
        resposta.headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=(self)"
        )
        resposta.headers.setdefault("Content-Security-Policy", self.CSP)
        return resposta


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Atribui um ID a cada requisição e registra duração e status."""

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        inicio = time.perf_counter()

        try:
            resposta = await call_next(request)
        except Exception:
            duracao = (time.perf_counter() - inicio) * 1000
            logger.exception(
                "[%s] %s %s falhou após %.1fms",
                request_id,
                request.method,
                request.url.path,
                duracao,
            )
            raise

        duracao = (time.perf_counter() - inicio) * 1000
        resposta.headers["X-Request-ID"] = request_id
        resposta.headers["X-Response-Time"] = f"{duracao:.1f}ms"

        if request.url.path.startswith("/api/"):
            nivel = logging.WARNING if resposta.status_code >= 400 else logging.DEBUG
            logger.log(
                nivel,
                "[%s] %s %s -> %d (%.1fms)",
                request_id,
                request.method,
                request.url.path,
                resposta.status_code,
                duracao,
            )
        return resposta


def _ip_cliente(request: Request) -> str:
    """IP real do cliente, considerando proxy reverso à frente da aplicação."""
    encaminhado = request.headers.get("x-forwarded-for")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"
