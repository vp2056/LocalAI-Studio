"""Rotas de documentos, RAG e embeddings."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile
from sqlalchemy import func, select

from ...config import settings
from ...core.exceptions import ArquivoInvalido, RecursoNaoEncontrado
from ...database.models import Document
from ...schemas import (
    BuscaRagIn,
    DocumentoOut,
    EmbeddingsIn,
    EmbeddingsOut,
    MensagemSimples,
    PaginaOut,
    ResultadoRagOut,
)
from ...services.rag.embeddings import servico_embeddings
from ...services.rag.pipeline import pipeline
from ..deps import BancoDados, Pagina, UsuarioAtual

logger = logging.getLogger(__name__)
router = APIRouter(tags=["RAG e Documentos"])

BLOCO_UPLOAD = 4 * 1024 * 1024


# ===========================================================================
# Upload e documentos
# ===========================================================================
@router.post("/upload", response_model=DocumentoOut, status_code=201)
async def enviar_documento(
    db: BancoDados,
    usuario: UsuarioAtual,
    tarefas: BackgroundTasks,
    arquivo: UploadFile = File(...),
    colecao: Annotated[str, Form()] = "default",
    indexar: Annotated[bool, Form()] = True,
):
    """
    Envia um documento e o coloca na fila de indexação.

    A indexação roda em segundo plano: arquivos grandes não devem manter a
    requisição HTTP aberta.
    """
    nome = Path(arquivo.filename or "documento.txt").name
    extensao = Path(nome).suffix.lower()

    if extensao not in settings.allowed_document_ext:
        raise ArquivoInvalido(
            f"Formato '{extensao}' não suportado. "
            f"Aceitos: {', '.join(settings.allowed_document_ext)}"
        )

    destino = settings.caminho("documents") / nome
    # Evita sobrescrever homônimos: acrescenta um sufixo numérico.
    contador = 1
    while destino.exists():
        destino = settings.caminho("documents") / f"{Path(nome).stem}_{contador}{extensao}"
        contador += 1

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
        destino.unlink(missing_ok=True)
        raise

    if not indexar:
        documento = Document(
            user_id=usuario.id,
            title=Path(nome).stem,
            filename=destino.name,
            path=str(destino),
            filetype=extensao.lstrip("."),
            size_bytes=total,
            collection=colecao,
            status="pending",
        )
        db.add(documento)
        db.commit()
        return documento

    documento = pipeline.indexar_arquivo(
        destino, colecao=colecao, user_id=usuario.id
    )
    return db.get(Document, documento.id)


@router.get("/documents", response_model=PaginaOut)
def listar_documentos(
    db: BancoDados,
    usuario: UsuarioAtual,
    pagina: Pagina,
    colecao: str | None = None,
    status: str | None = None,
    busca: Annotated[str | None, Query(max_length=200)] = None,
):
    """Lista os documentos da base de conhecimento."""
    condicoes = []
    if colecao:
        condicoes.append(Document.collection == colecao)
    if status:
        condicoes.append(Document.status == status)
    if busca:
        condicoes.append(Document.title.ilike(f"%{busca}%"))

    total = db.scalar(select(func.count(Document.id)).where(*condicoes)) or 0
    documentos = db.scalars(
        select(Document)
        .where(*condicoes)
        .order_by(Document.created_at.desc())
        .offset(pagina.offset)
        .limit(pagina.per_page)
    ).all()

    return pagina.envelope(
        [DocumentoOut.model_validate(d) for d in documentos], total
    )


@router.get("/documents/{documento_id}", response_model=DocumentoOut)
def obter_documento(documento_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Detalhes de um documento."""
    documento = db.get(Document, documento_id)
    if documento is None:
        raise RecursoNaoEncontrado("Documento não encontrado.")
    return documento


@router.post("/documents/{documento_id}/reindex", response_model=DocumentoOut)
def reindexar(documento_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Reprocessa o documento (após trocar o modelo de embeddings, por exemplo)."""
    documento = db.get(Document, documento_id)
    if documento is None:
        raise RecursoNaoEncontrado("Documento não encontrado.")

    atualizado = pipeline.indexar_arquivo(
        documento.path,
        colecao=documento.collection,
        user_id=documento.user_id,
        reindexar=True,
    )
    return db.get(Document, atualizado.id)


@router.delete("/documents/{documento_id}", response_model=MensagemSimples)
def remover_documento(
    documento_id: int, db: BancoDados, usuario: UsuarioAtual, apagar_arquivo: bool = False
):
    """Remove o documento, seus embeddings e opcionalmente o arquivo."""
    documento = db.get(Document, documento_id)
    if documento is None:
        raise RecursoNaoEncontrado("Documento não encontrado.")

    caminho = Path(documento.path)
    pipeline.remover_documento(documento_id)

    if apagar_arquivo and caminho.exists():
        try:
            caminho.resolve().relative_to(settings.caminho("documents").resolve())
            caminho.unlink()
        except ValueError:
            logger.warning("Arquivo fora de documents/ preservado: %s", caminho)

    return MensagemSimples(detail="Documento removido.")


@router.get("/documents/collections/list")
def listar_colecoes(db: BancoDados, usuario: UsuarioAtual):
    """Coleções existentes com a contagem de documentos."""
    linhas = db.execute(
        select(
            Document.collection,
            func.count(Document.id),
            func.sum(Document.chunk_count),
        ).group_by(Document.collection)
    ).all()
    return [
        {"name": nome, "documents": qtd, "chunks": int(trechos or 0)}
        for nome, qtd, trechos in linhas
    ]


# ===========================================================================
# Busca e embeddings
# ===========================================================================
@router.post("/rag/search", response_model=list[ResultadoRagOut])
def buscar(dados: BuscaRagIn, usuario: UsuarioAtual):
    """Busca semântica na base de conhecimento."""
    resultados = pipeline.buscar(
        dados.consulta,
        k=dados.k,
        colecoes=dados.colecoes,
        score_minimo=dados.score_minimo,
    )
    return [
        ResultadoRagOut(
            embedding_id=r.embedding_id,
            score=r.score,
            content=r.content,
            document_id=r.document_id,
            document_title=r.document_title,
            collection=r.collection,
            meta=r.meta or {},
        )
        for r in resultados
    ]


@router.post("/embeddings", response_model=EmbeddingsOut)
def gerar_embeddings(dados: EmbeddingsIn, usuario: UsuarioAtual):
    """Gera vetores para uma lista de textos."""
    vetores = servico_embeddings.codificar(dados.textos)
    return EmbeddingsOut(
        vetores=vetores.tolist(),
        modelo=servico_embeddings.nome,
        dimensao=servico_embeddings.dim,
    )


@router.get("/rag/stats")
def estatisticas(db: BancoDados, usuario: UsuarioAtual):
    """Números da base de conhecimento e do índice vetorial."""
    return pipeline.estatisticas(db)


@router.post("/rag/rebuild", response_model=MensagemSimples)
def reconstruir(usuario: UsuarioAtual):
    """Reconstrói o índice vetorial a partir do banco."""
    total = pipeline.reconstruir()
    return MensagemSimples(detail=f"Índice reconstruído com {total} vetores.")


@router.post("/rag/import-folder", response_model=list[DocumentoOut])
def importar_pasta(
    caminho: str,
    usuario: UsuarioAtual,
    db: BancoDados,
    colecao: str = "default",
    recursivo: bool = True,
):
    """Importa e indexa todos os documentos suportados de uma pasta."""
    pasta = Path(caminho).expanduser()
    if not pasta.is_dir():
        raise ArquivoInvalido(f"Pasta não encontrada: {caminho}")

    padrao = "**/*" if recursivo else "*"
    importados: list[Document] = []
    falhas: list[str] = []

    for arquivo in sorted(pasta.glob(padrao)):
        if not arquivo.is_file():
            continue
        if arquivo.suffix.lower() not in settings.allowed_document_ext:
            continue
        try:
            documento = pipeline.indexar_arquivo(
                arquivo, colecao=colecao, user_id=usuario.id
            )
            importados.append(documento)
        except Exception as exc:
            # Uma falha isolada não deve abortar a importação em lote.
            logger.warning("Falha ao importar %s: %s", arquivo.name, exc)
            falhas.append(arquivo.name)

    if falhas:
        logger.warning("Documentos com falha na importação: %s", ", ".join(falhas))

    return [DocumentoOut.model_validate(d) for d in importados]
