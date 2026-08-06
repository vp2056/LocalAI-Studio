"""Rotas de sistema: painel, monitor, configurações, logs, favoritos e backup."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select

from ...config import settings
from ...core.exceptions import RecursoNaoEncontrado
from ...database.models import (
    AIModel,
    Agent,
    Conversation,
    Document,
    Embedding,
    Favorite,
    Log,
    Message,
    Plugin,
    Setting,
)
from ...schemas import (
    ConfiguracaoIn,
    ConfiguracaoOut,
    FavoritoIn,
    FavoritoOut,
    LogOut,
    MensagemSimples,
    PaginaOut,
)
from ...services.backup.service import servico_backup
from ...services.extras.media import estado_extras
from ...services.llm.manager import gerenciador
from ...services.plugins.manager import gerenciador_plugins
from ...services.rag.pipeline import pipeline
from ...services.system.monitor import monitor
from ..deps import BancoDados, Pagina, UsuarioAdmin, UsuarioAtual

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Sistema"])


# ===========================================================================
# Painel e monitor
# ===========================================================================
@router.get("/system")
def informacoes(db: BancoDados, usuario: UsuarioAtual):
    """Visão geral do sistema: recursos, contagens e subsistemas."""
    return {
        "app": {
            "name": settings.app_name,
            "version": settings.version,
            "mode": settings.mode,
            "auth_required": settings.auth_required,
        },
        "resources": monitor.coletar(),
        "counts": _contagens(db),
        "models": gerenciador.estado(),
        "rag": pipeline.estatisticas(db),
        "plugins": gerenciador_plugins.estado(),
        "extras": estado_extras(),
    }


@router.get("/system/monitor")
def recursos(usuario: UsuarioAtual, completo: bool = False):
    """Métricas de CPU/RAM/GPU/disco para o painel em tempo real."""
    return monitor.coletar() if completo else monitor.resumo()


@router.get("/system/stats")
def contagens(db: BancoDados, usuario: UsuarioAtual):
    """Contagens das principais entidades."""
    return _contagens(db)


def _contagens(db) -> dict:
    """Totais exibidos nos cartões do painel."""
    return {
        "models": db.scalar(
            select(func.count(AIModel.id)).where(AIModel.is_available.is_(True))
        )
        or 0,
        "conversations": db.scalar(select(func.count(Conversation.id))) or 0,
        "messages": db.scalar(select(func.count(Message.id))) or 0,
        "documents": db.scalar(select(func.count(Document.id))) or 0,
        "embeddings": db.scalar(select(func.count(Embedding.id))) or 0,
        "agents": db.scalar(select(func.count(Agent.id))) or 0,
        "plugins": db.scalar(
            select(func.count(Plugin.id)).where(Plugin.enabled.is_(True))
        )
        or 0,
    }


@router.get("/health")
def saude():
    """Verificação de disponibilidade (não exige autenticação)."""
    return {"status": "ok", "version": settings.version}


# ===========================================================================
# Configurações
# ===========================================================================
@router.get("/settings", response_model=list[ConfiguracaoOut])
def listar_configuracoes(db: BancoDados, usuario: UsuarioAtual, categoria: str | None = None):
    """Configurações persistidas."""
    consulta = select(Setting)
    if categoria:
        consulta = consulta.where(Setting.category == categoria)
    return db.scalars(consulta.order_by(Setting.category, Setting.key)).all()


@router.put("/settings/{chave:path}", response_model=ConfiguracaoOut)
def gravar_configuracao(
    chave: str, dados: ConfiguracaoIn, db: BancoDados, usuario: UsuarioAtual
):
    """Cria ou atualiza uma configuração."""
    registro = db.scalar(select(Setting).where(Setting.key == chave))
    if registro is None:
        registro = Setting(key=chave, value=dados.value, category=chave.split(".")[0])
        db.add(registro)
    else:
        registro.value = dados.value
    db.commit()
    return registro


@router.get("/settings/runtime/config")
def configuracao_runtime(usuario: UsuarioAtual):
    """Configuração efetiva do servidor (sem segredos)."""
    dados = settings.model_dump()
    dados.pop("secret_key", None)
    dados["database_url"] = "sqlite:///<oculto>"
    return dados


# ===========================================================================
# Logs
# ===========================================================================
@router.get("/logs", response_model=PaginaOut)
def listar_logs(
    db: BancoDados,
    usuario: UsuarioAtual,
    pagina: Pagina,
    nivel: Annotated[str | None, Query(max_length=16)] = None,
    origem: Annotated[str | None, Query(max_length=120)] = None,
    busca: Annotated[str | None, Query(max_length=200)] = None,
):
    """Logs do sistema registrados no banco."""
    condicoes = []
    if nivel:
        condicoes.append(Log.level == nivel.upper())
    if origem:
        condicoes.append(Log.source.ilike(f"%{origem}%"))
    if busca:
        condicoes.append(Log.message.ilike(f"%{busca}%"))

    total = db.scalar(select(func.count(Log.id)).where(*condicoes)) or 0
    registros = db.scalars(
        select(Log)
        .where(*condicoes)
        .order_by(Log.id.desc())
        .offset(pagina.offset)
        .limit(pagina.per_page)
    ).all()

    return pagina.envelope([LogOut.model_validate(r) for r in registros], total)


@router.delete("/logs", response_model=MensagemSimples)
def limpar_logs(db: BancoDados, usuario: UsuarioAdmin):
    """Apaga todos os logs armazenados no banco."""
    total = db.scalar(select(func.count(Log.id))) or 0
    db.execute(delete(Log))
    db.commit()
    return MensagemSimples(detail=f"{total} registro(s) removido(s).")


# ===========================================================================
# Favoritos
# ===========================================================================
@router.get("/favorites", response_model=list[FavoritoOut])
def listar_favoritos(db: BancoDados, usuario: UsuarioAtual, tipo: str | None = None):
    """Itens favoritados pelo usuário."""
    condicoes = [Favorite.user_id == usuario.id]
    if tipo:
        condicoes.append(Favorite.target_type == tipo)
    return db.scalars(
        select(Favorite).where(*condicoes).order_by(Favorite.created_at.desc())
    ).all()


@router.post("/favorites", response_model=FavoritoOut, status_code=201)
def favoritar(dados: FavoritoIn, db: BancoDados, usuario: UsuarioAtual):
    """Adiciona um item aos favoritos (idempotente)."""
    existente = db.scalar(
        select(Favorite).where(
            Favorite.user_id == usuario.id,
            Favorite.target_type == dados.target_type,
            Favorite.target_id == dados.target_id,
        )
    )
    if existente:
        return existente

    favorito = Favorite(user_id=usuario.id, **dados.model_dump())
    db.add(favorito)
    db.commit()
    return favorito


@router.delete("/favorites/{favorito_id}", response_model=MensagemSimples)
def desfavoritar(favorito_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Remove um favorito."""
    favorito = db.get(Favorite, favorito_id)
    if favorito is None or favorito.user_id != usuario.id:
        raise RecursoNaoEncontrado("Favorito não encontrado.")
    db.delete(favorito)
    db.commit()
    return MensagemSimples(detail="Favorito removido.")


# ===========================================================================
# Backup
# ===========================================================================
@router.get("/backup")
def listar_backups(usuario: UsuarioAtual):
    """Backups existentes."""
    return servico_backup.listar()


@router.post("/backup", status_code=201)
def criar_backup(
    usuario: UsuarioAdmin, incluir_documentos: bool = True, rotulo: str | None = None
):
    """Cria um backup agora."""
    caminho = servico_backup.criar(
        incluir_documentos=incluir_documentos, rotulo=rotulo
    )
    return {
        "filename": caminho.name,
        "size_mb": round(caminho.stat().st_size / 1024 / 1024, 2),
    }


@router.get("/backup/{nome_arquivo}/download")
def baixar_backup(nome_arquivo: str, usuario: UsuarioAdmin):
    """Baixa um arquivo de backup."""
    caminho = servico_backup._resolver(nome_arquivo)
    return FileResponse(
        caminho, filename=caminho.name, media_type="application/zip"
    )


@router.post("/backup/{nome_arquivo}/restore", response_model=MensagemSimples)
def restaurar_backup(
    nome_arquivo: str, usuario: UsuarioAdmin, restaurar_documentos: bool = True
):
    """
    Restaura um backup.

    Operação destrutiva: um backup de segurança é criado automaticamente antes,
    e o servidor precisa ser reiniciado depois.
    """
    servico_backup.restaurar(
        nome_arquivo, restaurar_documentos=restaurar_documentos
    )
    return MensagemSimples(
        detail="Backup restaurado. Reinicie o servidor para aplicar."
    )


@router.delete("/backup/{nome_arquivo}", response_model=MensagemSimples)
def remover_backup(nome_arquivo: str, usuario: UsuarioAdmin):
    """Exclui um arquivo de backup."""
    servico_backup.remover(nome_arquivo)
    return MensagemSimples(detail="Backup removido.")
