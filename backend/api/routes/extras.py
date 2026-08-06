"""Rotas dos recursos extras: OCR, voz (STT/TTS) e geração de imagens."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from ...config import settings
from ...core.exceptions import ArquivoInvalido
from ...schemas import GerarImagemIn, TTSIn
from ...services.extras.media import (
    estado_extras,
    servico_imagens,
    servico_ocr,
    servico_stt,
    servico_tts,
)
from ..deps import UsuarioAtual

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/extras", tags=["Extras"])

EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".pdf"}
EXTENSOES_AUDIO = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".opus"}


@router.get("/status")
def estado(usuario: UsuarioAtual):
    """Disponibilidade de cada recurso extra."""
    return estado_extras()


# ------------------------------------------------------------------------ OCR
@router.post("/ocr")
async def ocr(
    usuario: UsuarioAtual, arquivo: UploadFile = File(...), idioma: str | None = None
):
    """Extrai texto de uma imagem ou de um PDF digitalizado."""
    caminho = await _salvar_temporario(arquivo, EXTENSOES_IMAGEM)
    try:
        return servico_ocr.extrair(caminho, idioma=idioma)
    finally:
        caminho.unlink(missing_ok=True)


# ------------------------------------------------------------------------ STT
@router.post("/transcribe")
async def transcrever(
    usuario: UsuarioAtual, arquivo: UploadFile = File(...), idioma: str = "pt"
):
    """Transcreve um arquivo de áudio."""
    caminho = await _salvar_temporario(arquivo, EXTENSOES_AUDIO)
    try:
        return servico_stt.transcrever(caminho, idioma=idioma)
    finally:
        caminho.unlink(missing_ok=True)


# ------------------------------------------------------------------------ TTS
@router.post("/tts")
def sintetizar(dados: TTSIn, usuario: UsuarioAtual):
    """Converte texto em áudio e devolve o arquivo .wav."""
    caminho = servico_tts.sintetizar(dados.texto, voz=dados.voz)
    return FileResponse(caminho, media_type="audio/wav", filename=caminho.name)


@router.get("/tts/voices")
def vozes(usuario: UsuarioAtual):
    """Vozes disponíveis para síntese."""
    return servico_tts.vozes()


# -------------------------------------------------------------------- imagens
@router.post("/images/generate")
def gerar_imagem(dados: GerarImagemIn, usuario: UsuarioAtual):
    """Gera uma imagem a partir de um prompt textual."""
    return servico_imagens.gerar(
        dados.prompt,
        modelo=dados.modelo,
        prompt_negativo=dados.prompt_negativo,
        largura=dados.largura,
        altura=dados.altura,
        passos=dados.passos,
        escala=dados.escala,
        semente=dados.semente,
    )


@router.get("/images/models")
def modelos_imagem(usuario: UsuarioAtual):
    """Modelos de difusão instalados."""
    return servico_imagens.modelos()


@router.get("/images/{nome_arquivo}")
def obter_imagem(nome_arquivo: str, usuario: UsuarioAtual):
    """Devolve uma imagem gerada anteriormente."""
    caminho = (settings.caminho("uploads") / Path(nome_arquivo).name).resolve()
    try:
        caminho.relative_to(settings.caminho("uploads").resolve())
    except ValueError:
        raise ArquivoInvalido("Nome de arquivo inválido.")
    if not caminho.exists():
        raise ArquivoInvalido("Imagem não encontrada.")
    return FileResponse(caminho)


async def _salvar_temporario(arquivo: UploadFile, permitidas: set[str]) -> Path:
    """Grava o upload em ``temp/`` validando a extensão e o tamanho."""
    nome = Path(arquivo.filename or "arquivo").name
    extensao = Path(nome).suffix.lower()

    if extensao not in permitidas:
        raise ArquivoInvalido(
            f"Formato '{extensao}' não suportado. "
            f"Aceitos: {', '.join(sorted(permitidas))}"
        )

    destino = settings.caminho("temp") / f"upload_{nome}"
    limite = settings.max_upload_mb * 1024 * 1024
    total = 0

    try:
        with destino.open("wb") as saida:
            while pedaco := await arquivo.read(4 * 1024 * 1024):
                total += len(pedaco)
                if total > limite:
                    raise ArquivoInvalido(
                        f"Arquivo excede o limite de {settings.max_upload_mb} MB."
                    )
                saida.write(pedaco)
    except Exception:
        destino.unlink(missing_ok=True)
        raise

    return destino
