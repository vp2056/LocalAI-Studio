"""
Dependências compartilhadas pelas rotas: autenticação e paginação.

Três formas de autenticação são aceitas:
  1. ``Authorization: Bearer <jwt>``   — interface web e clientes;
  2. ``X-API-Key: lais_…``             — integrações externas;
  3. cookie ``lais_token``             — conveniência do navegador.

Com ``auth_required=False`` (modos desktop/portátil de usuário único), o
primeiro usuário do banco é assumido automaticamente.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Cookie, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..core.exceptions import PermissaoNegada
from ..core.security import decodificar_token, hash_api_key
from ..database.base import agora
from ..database.models import ApiKey, Session as SessaoLogin, User
from ..database.session import get_db

logger = logging.getLogger(__name__)

NOME_COOKIE_TOKEN = "lais_token"


def _do_cabecalho(authorization: str | None) -> str | None:
    """Extrai o token de um cabeçalho ``Bearer``."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def usuario_atual(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    lais_token: Annotated[str | None, Cookie()] = None,
) -> User:
    """Resolve o usuário autenticado ou recusa a requisição."""
    # Modo de usuário único: dispensa credenciais.
    if not settings.auth_required:
        usuario = db.scalar(select(User).order_by(User.id).limit(1))
        if usuario:
            return usuario

    if x_api_key:
        return _por_api_key(db, x_api_key)

    token = _do_cabecalho(authorization) or lais_token
    if not token:
        raise PermissaoNegada("Autenticação necessária.")

    return _por_jwt(db, token, request)


def _por_jwt(db: Session, token: str, request: Request) -> User:
    dados = decodificar_token(token)
    if dados is None:
        raise PermissaoNegada("Token inválido ou expirado.")

    # A sessão precisa existir e não estar revogada (logout real).
    sessao_login = db.scalar(
        select(SessaoLogin).where(SessaoLogin.token_id == dados["jti"])
    )
    if sessao_login is None or sessao_login.revoked:
        raise PermissaoNegada("Sessão encerrada. Entre novamente.")

    usuario = db.get(User, int(dados["sub"]))
    if usuario is None or not usuario.is_active:
        raise PermissaoNegada("Usuário inativo ou inexistente.")

    request.state.session_id = sessao_login.id
    return usuario


def _por_api_key(db: Session, chave: str) -> User:
    registro = db.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == hash_api_key(chave), ApiKey.is_active.is_(True)
        )
    )
    if registro is None:
        raise PermissaoNegada("Chave de API inválida.")

    if registro.expires_at and registro.expires_at < agora():
        raise PermissaoNegada("Chave de API expirada.")

    registro.last_used_at = agora()
    db.commit()

    usuario = db.get(User, registro.user_id)
    if usuario is None or not usuario.is_active:
        raise PermissaoNegada("Usuário da chave está inativo.")
    return usuario


def usuario_admin(
    usuario: Annotated[User, Depends(usuario_atual)],
) -> User:
    """Exige papel de administrador."""
    if not usuario.is_admin:
        raise PermissaoNegada("Esta operação exige privilégios de administrador.")
    return usuario


def usuario_websocket(db: Session, token: str | None) -> User | None:
    """
    Autentica uma conexão WebSocket.

    O navegador não permite cabeçalhos personalizados no handshake, então o
    token chega por query string.
    """
    if not settings.auth_required:
        return db.scalar(select(User).order_by(User.id).limit(1))

    if not token:
        return None

    dados = decodificar_token(token)
    if dados is None:
        return None

    sessao_login = db.scalar(
        select(SessaoLogin).where(SessaoLogin.token_id == dados["jti"])
    )
    if sessao_login is None or sessao_login.revoked:
        return None

    usuario = db.get(User, int(dados["sub"]))
    return usuario if usuario and usuario.is_active else None


class Paginacao:
    """Parâmetros de paginação comuns a várias listagens."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        per_page: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> None:
        self.page = page
        self.per_page = per_page
        self.offset = (page - 1) * per_page

    def envelope(self, itens: list, total: int) -> dict:
        """Monta a resposta paginada padrão."""
        return {
            "items": itens,
            "total": total,
            "page": self.page,
            "per_page": self.per_page,
            "pages": max(1, -(-total // self.per_page)),  # divisão com teto
        }


# Aliases usados nas assinaturas das rotas.
UsuarioAtual = Annotated[User, Depends(usuario_atual)]
UsuarioAdmin = Annotated[User, Depends(usuario_admin)]
BancoDados = Annotated[Session, Depends(get_db)]
Pagina = Annotated[Paginacao, Depends()]
