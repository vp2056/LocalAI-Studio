"""Rotas de gerenciamento de modelos de IA."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from sqlalchemy import select

from ...config import settings
from ...core.exceptions import ArquivoInvalido, ModeloNaoEncontrado
from ...database.models import AIModel
from ...schemas import (
    AtualizarModeloIn,
    BaixarModeloIn,
    DownloadOut,
    ImportarModeloIn,
    MensagemSimples,
    ModeloOut,
)
from ...services.llm.downloader import gerenciador_downloads
from ...services.llm.manager import gerenciador
from ..deps import BancoDados, UsuarioAtual

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/models", tags=["Modelos"])

# Blocos de 8 MB ao gravar uploads: equilibra memória e chamadas de I/O.
BLOCO_UPLOAD = 8 * 1024 * 1024


@router.get("", response_model=list[ModeloOut])
def listar(db: BancoDados, usuario: UsuarioAtual, incluir_indisponiveis: bool = False):
    """Lista os modelos registrados."""
    consulta = select(AIModel)
    if not incluir_indisponiveis:
        consulta = consulta.where(AIModel.is_available.is_(True))
    return db.scalars(consulta.order_by(AIModel.name)).all()


@router.post("/scan", response_model=list[ModeloOut])
def escanear(db: BancoDados, usuario: UsuarioAtual):
    """Reexamina a pasta ``models/`` em busca de novidades."""
    gerenciador.escanear()
    return db.scalars(
        select(AIModel).where(AIModel.is_available.is_(True)).order_by(AIModel.name)
    ).all()


@router.get("/status")
def estado(usuario: UsuarioAtual):
    """Modelos carregados em memória e backends disponíveis."""
    return gerenciador.estado()


@router.get("/{modelo_id}", response_model=ModeloOut)
def obter(modelo_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Detalhes técnicos de um modelo."""
    modelo = db.get(AIModel, modelo_id)
    if modelo is None:
        raise ModeloNaoEncontrado("Modelo não encontrado.")
    return modelo


@router.patch("/{modelo_id}", response_model=ModeloOut)
def atualizar(
    modelo_id: int, dados: AtualizarModeloIn, db: BancoDados, usuario: UsuarioAtual
):
    """Edita metadados e parâmetros padrão do modelo."""
    modelo = db.get(AIModel, modelo_id)
    if modelo is None:
        raise ModeloNaoEncontrado("Modelo não encontrado.")

    campos = dados.model_dump(exclude_none=True)

    # Só pode haver um modelo padrão por vez.
    if campos.get("is_default"):
        for outro in db.scalars(
            select(AIModel).where(AIModel.is_default.is_(True))
        ).all():
            outro.is_default = False

    for campo, valor in campos.items():
        setattr(modelo, campo, valor)
    db.commit()
    return modelo


@router.post("/import", response_model=ModeloOut, status_code=201)
def importar(dados: ImportarModeloIn, db: BancoDados, usuario: UsuarioAtual):
    """
    Importa um modelo já existente no disco.

    Com ``copiar=false`` apenas registra o caminho original — útil para
    arquivos grandes em outra partição.
    """
    origem = Path(dados.caminho).expanduser()
    if not origem.exists():
        raise ArquivoInvalido(f"Caminho não encontrado: {origem}")

    if origem.is_file() and origem.suffix.lower() not in settings.allowed_model_ext:
        raise ArquivoInvalido(
            f"Extensão '{origem.suffix}' não suportada. "
            f"Aceitas: {', '.join(settings.allowed_model_ext)}"
        )

    if dados.copiar:
        destino = settings.caminho("models") / (dados.nome or origem.name)
        if destino.exists():
            raise ArquivoInvalido(f"Já existe um modelo chamado '{destino.name}'.")

        logger.info("Copiando modelo para %s…", destino)
        if origem.is_dir():
            shutil.copytree(origem, destino)
        else:
            shutil.copy2(origem, destino)
        alvo = destino
    else:
        alvo = origem

    gerenciador.escanear()

    modelo = db.scalar(select(AIModel).where(AIModel.path == str(alvo)))
    if modelo is None:
        # Caminho fora de models/ com copiar=false: registra manualmente.
        info = (
            gerenciador._info_gguf(alvo)
            if alvo.suffix.lower() == ".gguf"
            else gerenciador._info_hf(alvo)
            if alvo.is_dir()
            else gerenciador._info_onnx(alvo)
        )
        modelo = AIModel(
            name=dados.nome or info.name,
            path=info.path,
            format=info.format,
            backend=info.backend,
            kind=info.kind,
            size_bytes=info.size_bytes,
            quantization=info.quantization,
            parameters=info.parameters,
            architecture=info.architecture,
            context_length=info.context_length,
            meta=info.meta,
        )
        db.add(modelo)
        db.commit()

    logger.info("Modelo importado: %s", modelo.name)
    return modelo


@router.post("/upload", response_model=ModeloOut, status_code=201)
async def enviar(
    db: BancoDados, usuario: UsuarioAtual, arquivo: UploadFile = File(...)
):
    """Envia um arquivo de modelo pelo navegador."""
    nome = Path(arquivo.filename or "modelo.gguf").name
    extensao = Path(nome).suffix.lower()

    if extensao not in settings.allowed_model_ext:
        raise ArquivoInvalido(
            f"Extensão '{extensao}' não permitida. "
            f"Aceitas: {', '.join(settings.allowed_model_ext)}"
        )

    destino = settings.caminho("models") / nome
    if destino.exists():
        raise ArquivoInvalido(f"Já existe um modelo chamado '{nome}'.")

    limite = settings.max_upload_mb * 1024 * 1024
    total = 0

    try:
        with destino.open("wb") as saida:
            while pedaco := await arquivo.read(BLOCO_UPLOAD):
                total += len(pedaco)
                if total > limite:
                    raise ArquivoInvalido(
                        f"Arquivo excede o limite de {settings.max_upload_mb} MB."
                    )
                saida.write(pedaco)
    except Exception:
        destino.unlink(missing_ok=True)  # não deixa arquivo parcial para trás
        raise

    gerenciador.escanear()
    modelo = db.scalar(select(AIModel).where(AIModel.path == str(destino)))
    if modelo is None:
        raise ArquivoInvalido("O arquivo enviado não foi reconhecido como modelo.")
    return modelo


@router.delete("/{modelo_id}", response_model=MensagemSimples)
def remover(
    modelo_id: int, db: BancoDados, usuario: UsuarioAtual, apagar_arquivo: bool = False
):
    """Remove o registro do modelo e, opcionalmente, o arquivo do disco."""
    modelo = db.get(AIModel, modelo_id)
    if modelo is None:
        raise ModeloNaoEncontrado("Modelo não encontrado.")

    gerenciador.descarregar(modelo.name)
    caminho = Path(modelo.path)
    nome = modelo.name

    db.delete(modelo)
    db.commit()

    if apagar_arquivo and caminho.exists():
        # Só apaga dentro de models/: protege caminhos importados por referência.
        try:
            caminho.resolve().relative_to(settings.caminho("models").resolve())
        except ValueError:
            return MensagemSimples(
                detail=f"Modelo '{nome}' removido do catálogo. "
                "O arquivo está fora da pasta de modelos e foi preservado."
            )
        if caminho.is_dir():
            shutil.rmtree(caminho, ignore_errors=True)
        else:
            caminho.unlink(missing_ok=True)
        return MensagemSimples(detail=f"Modelo '{nome}' e arquivo removidos.")

    return MensagemSimples(detail=f"Modelo '{nome}' removido do catálogo.")


@router.post("/{modelo_id}/load", response_model=MensagemSimples)
def carregar(modelo_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Carrega o modelo em memória antecipadamente."""
    modelo = db.get(AIModel, modelo_id)
    if modelo is None:
        raise ModeloNaoEncontrado("Modelo não encontrado.")
    gerenciador.carregar(modelo.name)
    return MensagemSimples(detail=f"Modelo '{modelo.name}' carregado.")


@router.post("/{modelo_id}/unload", response_model=MensagemSimples)
def descarregar(modelo_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Libera a memória ocupada pelo modelo."""
    modelo = db.get(AIModel, modelo_id)
    if modelo is None:
        raise ModeloNaoEncontrado("Modelo não encontrado.")
    if gerenciador.descarregar(modelo.name):
        return MensagemSimples(detail=f"Modelo '{modelo.name}' descarregado.")
    return MensagemSimples(detail="O modelo não estava carregado.")


# ------------------------------------------------------------------ downloads
@router.post("/download", response_model=DownloadOut, status_code=202)
def baixar(dados: BaixarModeloIn, usuario: UsuarioAtual):
    """Inicia o download de um modelo a partir de uma URL."""
    return gerenciador_downloads.iniciar(dados.url, nome_arquivo=dados.nome_arquivo)


@router.get("/downloads/list", response_model=list[DownloadOut])
def listar_downloads(usuario: UsuarioAtual):
    """Downloads recentes e em andamento."""
    return gerenciador_downloads.listar()


@router.post("/downloads/{download_id}/cancel", response_model=MensagemSimples)
def cancelar_download(download_id: int, usuario: UsuarioAtual):
    """Cancela um download em andamento."""
    gerenciador_downloads.cancelar(download_id)
    return MensagemSimples(detail="Cancelamento solicitado.")
