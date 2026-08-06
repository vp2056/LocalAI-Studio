"""
Segurança: hash de senha, tokens JWT, chaves de API e proteção CSRF.

Decisões:
  * bcrypt via passlib quando disponível; caso contrário, PBKDF2-HMAC-SHA256
    da biblioteca padrão — assim a instalação mínima continua segura.
  * Cada JWT carrega um ``jti`` registrado na tabela ``sessions``, permitindo
    revogação individual (logout real, não apenas descarte do token no cliente).
  * Tokens CSRF usam o padrão "double submit cookie" com assinatura HMAC.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from ..config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hash de senha
# ---------------------------------------------------------------------------
# Usamos a biblioteca ``bcrypt`` diretamente em vez do passlib: o passlib está
# sem manutenção e quebra com bcrypt >= 4.1. Sem bcrypt, caímos para PBKDF2 da
# biblioteca padrão, que também é seguro.
try:
    import bcrypt as _bcrypt

    _BCRYPT = True
except ImportError:  # pragma: no cover - depende do ambiente
    _BCRYPT = False
    logger.warning("bcrypt indisponível; usando PBKDF2 da biblioteca padrão.")

_PBKDF2_ITERACOES = 260_000
_CUSTO_BCRYPT = 12


def hash_senha(senha: str) -> str:
    """Gera o hash de uma senha em texto puro."""
    if _BCRYPT:
        return _bcrypt.hashpw(
            _pre_hash(senha), _bcrypt.gensalt(rounds=_CUSTO_BCRYPT)
        ).decode()

    sal = secrets.token_bytes(16)
    derivada = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), sal, _PBKDF2_ITERACOES
    )
    return (
        f"pbkdf2_sha256${_PBKDF2_ITERACOES}$"
        f"{base64.b64encode(sal).decode()}${base64.b64encode(derivada).decode()}"
    )


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Confere uma senha contra o hash armazenado."""
    if hash_armazenado.startswith("pbkdf2_sha256$"):
        try:
            _, iteracoes, sal_b64, esperado_b64 = hash_armazenado.split("$")
            derivada = hashlib.pbkdf2_hmac(
                "sha256",
                senha.encode("utf-8"),
                base64.b64decode(sal_b64),
                int(iteracoes),
            )
            return hmac.compare_digest(derivada, base64.b64decode(esperado_b64))
        except (ValueError, TypeError):
            return False

    if not _BCRYPT:
        return False
    try:
        return _bcrypt.checkpw(_pre_hash(senha), hash_armazenado.encode())
    except (ValueError, TypeError):
        return False


def _pre_hash(senha: str) -> bytes:
    """
    Reduz a senha a um digest de 44 bytes.

    O bcrypt trunca silenciosamente em 72 bytes; pré-hashear garante que toda
    a senha contribua para o resultado, independentemente do tamanho.
    """
    return base64.b64encode(hashlib.sha256(senha.encode("utf-8")).digest())


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def criar_token(
    user_id: int,
    *,
    username: str,
    role: str = "user",
    expira_em_minutos: int | None = None,
) -> tuple[str, str, datetime]:
    """
    Emite um token de acesso.

    Retorna ``(token, jti, expiração)`` — o ``jti`` deve ser gravado em
    ``sessions`` para permitir revogação.
    """
    minutos = expira_em_minutos or settings.access_token_expire_minutes
    agora = datetime.now(timezone.utc)
    expira = agora + timedelta(minutes=minutos)
    jti = secrets.token_urlsafe(24)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "jti": jti,
        "iat": int(agora.timestamp()),
        "exp": int(expira.timestamp()),
        "iss": settings.app_name,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, jti, expira


def decodificar_token(token: str) -> dict[str, Any] | None:
    """Valida e decodifica um JWT. Retorna ``None`` se inválido ou expirado."""
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError:
        logger.debug("Token expirado.")
    except jwt.InvalidTokenError as exc:
        logger.debug("Token inválido: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Chaves de API
# ---------------------------------------------------------------------------
PREFIXO_API_KEY = "lais_"


def gerar_api_key() -> tuple[str, str, str]:
    """
    Cria uma chave de API.

    Retorna ``(chave_pura, hash, prefixo)``. A chave pura é mostrada uma única
    vez ao usuário; o banco guarda apenas o hash.
    """
    corpo = secrets.token_urlsafe(32)
    chave = f"{PREFIXO_API_KEY}{corpo}"
    return chave, hash_api_key(chave), chave[:12]


def hash_api_key(chave: str) -> str:
    """Hash determinístico da chave (permite busca direta por igualdade)."""
    return hashlib.sha256(
        f"{settings.secret_key}:{chave}".encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# CSRF (double submit cookie assinado)
# ---------------------------------------------------------------------------
_CSRF_VALIDADE_SEGUNDOS = 60 * 60 * 12


def gerar_csrf_token() -> str:
    """Gera um token CSRF assinado com validade limitada."""
    nonce = secrets.token_urlsafe(16)
    emissao = str(int(time.time()))
    assinatura = _assinar_csrf(nonce, emissao)
    return f"{nonce}.{emissao}.{assinatura}"


def validar_csrf_token(token: str | None) -> bool:
    """Confere assinatura e validade de um token CSRF."""
    if not token:
        return False
    partes = token.split(".")
    if len(partes) != 3:
        return False
    nonce, emissao, assinatura = partes
    if not hmac.compare_digest(assinatura, _assinar_csrf(nonce, emissao)):
        return False
    try:
        return (time.time() - int(emissao)) <= _CSRF_VALIDADE_SEGUNDOS
    except ValueError:
        return False


def _assinar_csrf(nonce: str, emissao: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        f"{nonce}.{emissao}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
