"""Rotas de autenticação: login, registro, sessão e chaves de API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from ...config import settings
from ...core.exceptions import PermissaoNegada
from ...core.middleware import NOME_COOKIE_CSRF
from ...core.security import (
    criar_token,
    gerar_api_key,
    gerar_csrf_token,
    hash_senha,
    verificar_senha,
)
from ...database.base import agora
from ...database.models import ApiKey, Session as SessaoLogin, User
from ...schemas import (
    LoginIn,
    MensagemSimples,
    RegistroIn,
    TokenOut,
    TrocaSenhaIn,
    UsuarioOut,
)
from ..deps import NOME_COOKIE_TOKEN, BancoDados, UsuarioAtual

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login", response_model=TokenOut)
def login(dados: LoginIn, request: Request, response: Response, db: BancoDados):
    """Autentica o usuário e emite um token de acesso."""
    usuario = db.scalar(select(User).where(User.username == dados.username))

    # Mesma mensagem para usuário inexistente e senha errada: não revela quais
    # nomes de usuário existem.
    if usuario is None or not verificar_senha(dados.password, usuario.password_hash):
        logger.warning("Tentativa de login falhou para '%s'", dados.username)
        raise PermissaoNegada("Usuário ou senha incorretos.")

    if not usuario.is_active:
        raise PermissaoNegada("Esta conta está desativada.")

    token, jti, expira = criar_token(
        usuario.id, username=usuario.username, role=usuario.role
    )

    db.add(
        SessaoLogin(
            user_id=usuario.id,
            token_id=jti,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:512],
            expires_at=expira,
        )
    )
    usuario.last_login = agora()
    db.commit()

    _definir_cookies(response, token, request)
    logger.info("Login: %s", usuario.username)

    return TokenOut(access_token=token, expires_at=expira, user=UsuarioOut.model_validate(usuario))


@router.post("/register", response_model=TokenOut, status_code=201)
def registrar(dados: RegistroIn, request: Request, response: Response, db: BancoDados):
    """
    Cria uma conta.

    O primeiro usuário registrado vira administrador; os demais são comuns.
    """
    if db.scalar(select(User).where(User.username == dados.username)):
        raise PermissaoNegada("Este nome de usuário já está em uso.")
    if dados.email and db.scalar(select(User).where(User.email == dados.email)):
        raise PermissaoNegada("Este e-mail já está cadastrado.")

    primeiro = db.scalar(select(User).limit(1)) is None

    usuario = User(
        username=dados.username,
        email=dados.email,
        full_name=dados.full_name,
        password_hash=hash_senha(dados.password),
        role="admin" if primeiro else "user",
    )
    db.add(usuario)
    db.flush()

    token, jti, expira = criar_token(
        usuario.id, username=usuario.username, role=usuario.role
    )
    db.add(SessaoLogin(user_id=usuario.id, token_id=jti, expires_at=expira))
    db.commit()

    _definir_cookies(response, token, request)
    logger.info("Novo usuário: %s (%s)", usuario.username, usuario.role)

    return TokenOut(access_token=token, expires_at=expira, user=UsuarioOut.model_validate(usuario))


@router.post("/logout", response_model=MensagemSimples)
def logout(request: Request, response: Response, usuario: UsuarioAtual, db: BancoDados):
    """Revoga a sessão atual."""
    sessao_id = getattr(request.state, "session_id", None)
    if sessao_id:
        sessao_login = db.get(SessaoLogin, sessao_id)
        if sessao_login:
            sessao_login.revoked = True
            db.commit()

    response.delete_cookie(NOME_COOKIE_TOKEN, path="/")
    return MensagemSimples(detail="Sessão encerrada.")


@router.post("/logout-todas", response_model=MensagemSimples)
def logout_todas(usuario: UsuarioAtual, db: BancoDados):
    """Revoga todas as sessões do usuário em todos os dispositivos."""
    sessoes = db.scalars(
        select(SessaoLogin).where(
            SessaoLogin.user_id == usuario.id, SessaoLogin.revoked.is_(False)
        )
    ).all()
    for sessao_login in sessoes:
        sessao_login.revoked = True
    db.commit()
    return MensagemSimples(detail=f"{len(sessoes)} sessão(ões) encerrada(s).")


@router.get("/me", response_model=UsuarioOut)
def eu(usuario: UsuarioAtual):
    """Dados do usuário autenticado."""
    return usuario


@router.patch("/me", response_model=UsuarioOut)
def atualizar_perfil(
    dados: dict, usuario: UsuarioAtual, db: BancoDados
):
    """Atualiza nome, avatar e preferências do próprio usuário."""
    permitidos = {"full_name", "avatar", "email", "preferences"}
    for campo, valor in dados.items():
        if campo in permitidos:
            setattr(usuario, campo, valor)
    db.commit()
    return usuario


@router.post("/senha", response_model=MensagemSimples)
def trocar_senha(dados: TrocaSenhaIn, usuario: UsuarioAtual, db: BancoDados):
    """Troca a senha, exigindo a atual."""
    if not verificar_senha(dados.senha_atual, usuario.password_hash):
        raise PermissaoNegada("A senha atual está incorreta.")

    usuario.password_hash = hash_senha(dados.senha_nova)

    # Encerra as demais sessões: senha trocada invalida acessos antigos.
    for sessao_login in db.scalars(
        select(SessaoLogin).where(
            SessaoLogin.user_id == usuario.id, SessaoLogin.revoked.is_(False)
        )
    ).all():
        sessao_login.revoked = True

    db.commit()
    return MensagemSimples(detail="Senha alterada. Entre novamente.")


@router.get("/csrf")
def obter_csrf(response: Response, request: Request):
    """Emite um token CSRF para o cliente (usado antes do login)."""
    token = gerar_csrf_token()
    response.set_cookie(
        NOME_COOKIE_CSRF,
        token,
        httponly=False,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=60 * 60 * 12,
        path="/",
    )
    return {"csrf_token": token}


# ---------------------------------------------------------------- API keys
@router.get("/api-keys")
def listar_chaves(usuario: UsuarioAtual, db: BancoDados):
    """Chaves de API do usuário (sem os valores secretos)."""
    chaves = db.scalars(select(ApiKey).where(ApiKey.user_id == usuario.id)).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "prefix": c.key_prefix,
            "scopes": c.scopes,
            "is_active": c.is_active,
            "created_at": c.created_at,
            "last_used_at": c.last_used_at,
        }
        for c in chaves
    ]


@router.post("/api-keys", status_code=201)
def criar_chave(dados: dict, usuario: UsuarioAtual, db: BancoDados):
    """
    Cria uma chave de API.

    A chave completa é retornada uma única vez — depois disso, apenas o hash
    permanece armazenado.
    """
    chave, hash_valor, prefixo = gerar_api_key()
    registro = ApiKey(
        user_id=usuario.id,
        name=(dados.get("name") or "Chave sem nome")[:120],
        key_hash=hash_valor,
        key_prefix=prefixo,
        scopes=dados.get("scopes") or [],
    )
    db.add(registro)
    db.commit()

    return {
        "id": registro.id,
        "name": registro.name,
        "key": chave,
        "prefix": prefixo,
        "aviso": "Guarde esta chave: ela não será exibida novamente.",
    }


@router.delete("/api-keys/{chave_id}", response_model=MensagemSimples)
def remover_chave(chave_id: int, usuario: UsuarioAtual, db: BancoDados):
    """Revoga uma chave de API."""
    registro = db.get(ApiKey, chave_id)
    if registro is None or registro.user_id != usuario.id:
        raise PermissaoNegada("Chave não encontrada.")
    db.delete(registro)
    db.commit()
    return MensagemSimples(detail="Chave revogada.")


def _definir_cookies(response: Response, token: str, request: Request) -> None:
    """Grava o cookie de sessão com as flags de segurança adequadas."""
    response.set_cookie(
        NOME_COOKIE_TOKEN,
        token,
        httponly=True,  # inacessível ao JavaScript: mitiga roubo por XSS
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
