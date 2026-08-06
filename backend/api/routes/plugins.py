"""Rotas do sistema de plugins e do marketplace local."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from sqlalchemy import select

from ...config import settings
from ...core.exceptions import PluginError
from ...database.models import Plugin
from ...schemas import MensagemSimples, PluginOut
from ...services.plugins.manager import gerenciador_plugins
from ..deps import BancoDados, UsuarioAdmin, UsuarioAtual

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plugins", tags=["Plugins"])


@router.get("", response_model=list[PluginOut])
def listar(db: BancoDados, usuario: UsuarioAtual):
    """Plugins instalados."""
    return db.scalars(select(Plugin).order_by(Plugin.name)).all()


@router.post("/scan", response_model=list[PluginOut])
def escanear(db: BancoDados, usuario: UsuarioAdmin):
    """Reexamina a pasta de plugins."""
    gerenciador_plugins.escanear()
    return db.scalars(select(Plugin).order_by(Plugin.name)).all()


@router.get("/marketplace")
def marketplace(usuario: UsuarioAtual):
    """Catálogo local de plugins disponíveis."""
    return gerenciador_plugins.marketplace()


@router.get("/status")
def estado(usuario: UsuarioAtual):
    """Resumo do subsistema de plugins."""
    return gerenciador_plugins.estado()


@router.post("/install", response_model=PluginOut, status_code=201)
async def instalar(
    db: BancoDados, usuario: UsuarioAdmin, arquivo: UploadFile = File(...)
):
    """Instala um plugin a partir de um arquivo .zip."""
    nome = Path(arquivo.filename or "plugin.zip").name
    if not nome.lower().endswith(".zip"):
        raise PluginError("Envie um arquivo .zip.")

    temporario = settings.caminho("temp") / nome
    try:
        conteudo = await arquivo.read()
        temporario.write_bytes(conteudo)
        manifesto = gerenciador_plugins.instalar_zip(temporario)
    finally:
        temporario.unlink(missing_ok=True)

    registro = db.scalar(select(Plugin).where(Plugin.slug == manifesto["slug"]))
    if registro is None:
        raise PluginError("O plugin foi extraído, mas não pôde ser registrado.")
    return registro


@router.post("/{slug}/enable", response_model=PluginOut)
def habilitar(slug: str, db: BancoDados, usuario: UsuarioAdmin):
    """Ativa um plugin e carrega seu código."""
    gerenciador_plugins.habilitar(slug)
    return db.scalar(select(Plugin).where(Plugin.slug == slug))


@router.post("/{slug}/disable", response_model=PluginOut)
def desabilitar(slug: str, db: BancoDados, usuario: UsuarioAdmin):
    """Desativa um plugin."""
    gerenciador_plugins.desabilitar(slug)
    return db.scalar(select(Plugin).where(Plugin.slug == slug))


@router.patch("/{slug}/config", response_model=PluginOut)
def configurar(slug: str, config: dict, db: BancoDados, usuario: UsuarioAdmin):
    """Grava a configuração específica de um plugin."""
    registro = db.scalar(select(Plugin).where(Plugin.slug == slug))
    if registro is None:
        raise PluginError(f"Plugin '{slug}' não encontrado.")
    registro.config = config
    db.commit()
    return registro


@router.delete("/{slug}", response_model=MensagemSimples)
def remover(slug: str, usuario: UsuarioAdmin):
    """Desinstala um plugin e apaga seus arquivos."""
    gerenciador_plugins.remover(slug)
    return MensagemSimples(detail=f"Plugin '{slug}' removido.")
