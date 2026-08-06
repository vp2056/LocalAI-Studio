"""
Pipeline RAG: ingestão, indexação e busca semântica.

Fluxo de ingestão:
    arquivo → extração de texto → chunking → embeddings → banco + índice

O índice vetorial é sempre derivável da tabela ``embeddings``; ``reconstruir``
regenera-o do zero (usado na inicialização e ao trocar de backend).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...config import settings
from ...core.exceptions import ArquivoInvalido, RecursoNaoEncontrado
from ...database.base import agora
from ...database.models import Document, Embedding
from ...database.session import sessao
from . import chunker, loaders
from .embeddings import servico_embeddings
from .vector_store import Resultado, VectorStore, criar_store

logger = logging.getLogger(__name__)

# Quantos vetores são lidos por vez ao reconstruir o índice.
LOTE_RECONSTRUCAO = 2048


class PipelineRAG:
    """Orquestra ingestão e busca da base de conhecimento."""

    def __init__(self) -> None:
        self._store: VectorStore | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------- índice
    @property
    def store(self) -> VectorStore:
        """Índice vetorial, criado e reconstruído sob demanda."""
        if self._store is None:
            with self._lock:
                if self._store is None:
                    self._store = criar_store(servico_embeddings.dim)
                    if self._store.tamanho() == 0:
                        self.reconstruir()
        return self._store

    def reconstruir(self) -> int:
        """Recria o índice a partir da tabela ``embeddings``."""
        store = self._store or criar_store(servico_embeddings.dim)
        store.limpar()

        total = 0
        with sessao() as db:
            deslocamento = 0
            while True:
                lote = db.execute(
                    select(Embedding.id, Embedding.vector, Embedding.dim)
                    .order_by(Embedding.id)
                    .offset(deslocamento)
                    .limit(LOTE_RECONSTRUCAO)
                ).all()
                if not lote:
                    break

                ids: list[int] = []
                vetores: list[np.ndarray] = []
                for eid, bruto, dim in lote:
                    # Vetores de dimensão divergente vêm de outro modelo de
                    # embedding; ignorá-los evita corromper o índice.
                    if dim != store.dim:
                        continue
                    ids.append(eid)
                    vetores.append(np.frombuffer(bruto, dtype=np.float32))

                if ids:
                    store.adicionar(ids, np.vstack(vetores))
                    total += len(ids)
                deslocamento += LOTE_RECONSTRUCAO

        store.salvar()
        self._store = store
        logger.info("Índice '%s' reconstruído com %d vetores.", store.nome, total)
        return total

    # ----------------------------------------------------------- ingestão
    def indexar_arquivo(
        self,
        caminho: str | Path,
        *,
        colecao: str = "default",
        user_id: int | None = None,
        titulo: str | None = None,
        reindexar: bool = False,
    ) -> Document:
        """
        Importa e indexa um arquivo.

        Se o mesmo conteúdo (checksum) já estiver indexado na coleção, o
        documento existente é devolvido sem reprocessar — salvo ``reindexar``.
        """
        caminho = Path(caminho)
        if not caminho.is_file():
            raise ArquivoInvalido(f"Arquivo não encontrado: {caminho}")

        checksum = _checksum(caminho)

        with sessao() as db:
            existente = db.scalar(
                select(Document).where(
                    Document.checksum == checksum, Document.collection == colecao
                )
            )
            if existente and not reindexar:
                logger.info("Documento já indexado: %s", existente.title)
                return existente

            documento = existente or Document(
                user_id=user_id,
                title=titulo or caminho.stem,
                filename=caminho.name,
                path=str(caminho),
                filetype=caminho.suffix.lower().lstrip("."),
                size_bytes=caminho.stat().st_size,
                checksum=checksum,
                collection=colecao,
            )
            documento.status = "processing"
            documento.error = None
            if existente is None:
                db.add(documento)
            db.flush()
            documento_id = documento.id

        try:
            self._processar(documento_id, caminho, colecao)
        except Exception as exc:
            logger.exception("Falha ao indexar %s", caminho.name)
            with sessao() as db:
                doc = db.get(Document, documento_id)
                if doc:
                    doc.status = "failed"
                    doc.error = str(exc)[:2000]
            raise

        with sessao() as db:
            return db.get(Document, documento_id)  # type: ignore[return-value]

    def _processar(self, documento_id: int, caminho: Path, colecao: str) -> None:
        """Extrai, divide, vetoriza e persiste os trechos de um documento."""
        # Materializa o índice ANTES de gravar: se ele ainda não existir, será
        # reconstruído a partir do banco, e os vetores desta chamada entrariam
        # duas vezes (uma pela reconstrução, outra pelo adicionar() ao final).
        store = self.store

        texto, metadados = loaders.extrair(caminho)
        trechos = chunker.dividir(texto, metadados_base={"source": caminho.name})

        if not trechos:
            raise ArquivoInvalido(
                f"Nenhum trecho utilizável extraído de '{caminho.name}'."
            )

        vetores = servico_embeddings.codificar([t.content for t in trechos])
        modelo = servico_embeddings.nome
        dim = servico_embeddings.dim

        with sessao() as db:
            # Reindexação: remove os vetores antigos do banco e do índice.
            antigos = db.scalars(
                select(Embedding.id).where(Embedding.document_id == documento_id)
            ).all()
            if antigos:
                store.remover(list(antigos))
                db.execute(
                    delete(Embedding).where(Embedding.document_id == documento_id)
                )

            registros = [
                Embedding(
                    document_id=documento_id,
                    collection=colecao,
                    chunk_index=trecho.index,
                    content=trecho.content,
                    vector=vetores[i].astype(np.float32).tobytes(),
                    dim=dim,
                    model_name=modelo,
                    meta=trecho.meta,
                )
                for i, trecho in enumerate(trechos)
            ]
            db.add_all(registros)
            db.flush()

            ids = [r.id for r in registros]

            documento = db.get(Document, documento_id)
            if documento:
                documento.status = "indexed"
                documento.chunk_count = len(trechos)
                documento.char_count = len(texto)
                documento.meta = metadados
                documento.indexed_at = agora()

        store.adicionar(ids, vetores)
        store.salvar()
        logger.info(
            "Documento %d indexado: %d trechos (%s).", documento_id, len(trechos), modelo
        )

    # -------------------------------------------------------------- busca
    def buscar(
        self,
        consulta: str,
        *,
        k: int | None = None,
        colecoes: list[str] | None = None,
        score_minimo: float | None = None,
        document_ids: list[int] | None = None,
    ) -> list[Resultado]:
        """
        Busca semântica na base indexada.

        Quando há filtro de coleção/documento, recuperamos um excedente de
        candidatos e filtramos depois — o índice não conhece esses metadados.
        """
        if not consulta.strip():
            return []

        k = k or settings.rag_top_k
        minimo = settings.rag_min_score if score_minimo is None else score_minimo
        tem_filtro = bool(colecoes or document_ids)
        # Excedente generoso para não perder resultados válidos após o filtro.
        k_bruto = k * 8 if tem_filtro else k * 2

        vetor = servico_embeddings.codificar_um(consulta)
        brutos = self.store.buscar(vetor, k_bruto)
        if not brutos:
            return []

        pontuacoes = dict(brutos)

        with sessao() as db:
            condicoes = [Embedding.id.in_(list(pontuacoes))]
            if colecoes:
                condicoes.append(Embedding.collection.in_(colecoes))
            if document_ids:
                condicoes.append(Embedding.document_id.in_(document_ids))

            linhas = db.execute(
                select(
                    Embedding.id,
                    Embedding.content,
                    Embedding.document_id,
                    Embedding.collection,
                    Embedding.meta,
                    Document.title,
                )
                .join(Document, Document.id == Embedding.document_id)
                .where(*condicoes)
            ).all()

        resultados = [
            Resultado(
                embedding_id=eid,
                score=round(pontuacoes.get(eid, 0.0), 4),
                content=conteudo,
                document_id=doc_id,
                document_title=titulo,
                collection=col,
                meta=meta or {},
            )
            for eid, conteudo, doc_id, col, meta, titulo in linhas
            if pontuacoes.get(eid, 0.0) >= minimo
        ]
        resultados.sort(key=lambda r: r.score, reverse=True)
        return resultados[:k]

    def montar_contexto(
        self,
        consulta: str,
        *,
        k: int | None = None,
        colecoes: list[str] | None = None,
        max_caracteres: int = 6000,
    ) -> tuple[str, list[Resultado]]:
        """
        Recupera trechos e formata um bloco de contexto pronto para o prompt.

        Retorna ``(texto_do_contexto, resultados)``; contexto vazio quando
        nada relevante é encontrado.
        """
        resultados = self.buscar(consulta, k=k, colecoes=colecoes)
        if not resultados:
            return "", []

        partes: list[str] = []
        usados: list[Resultado] = []
        total = 0

        for i, r in enumerate(resultados, start=1):
            origem = r.document_title or "documento"
            if pagina := (r.meta or {}).get("page"):
                origem = f"{origem}, p. {pagina}"
            bloco = f"[{i}] ({origem}) {r.content}"

            if total + len(bloco) > max_caracteres:
                break
            partes.append(bloco)
            usados.append(r)
            total += len(bloco)

        contexto = (
            "CONTEXTO recuperado da base de conhecimento:\n\n"
            + "\n\n".join(partes)
            + "\n\nUse este contexto para responder. Cite as fontes pelo número "
            "entre colchetes. Se a resposta não estiver no contexto, diga isso."
        )
        return contexto, usados

    # --------------------------------------------------------- manutenção
    def remover_documento(self, documento_id: int) -> None:
        """Exclui um documento, seus embeddings e as entradas do índice."""
        with sessao() as db:
            documento = db.get(Document, documento_id)
            if documento is None:
                raise RecursoNaoEncontrado("Documento não encontrado.")
            ids = db.scalars(
                select(Embedding.id).where(Embedding.document_id == documento_id)
            ).all()
            db.delete(documento)  # cascata remove os embeddings

        if ids:
            self.store.remover(list(ids))
            self.store.salvar()
        logger.info("Documento %d removido (%d vetores).", documento_id, len(ids))

    def estatisticas(self, db: Session | None = None) -> dict[str, Any]:
        """Números da base de conhecimento para o painel."""

        def coletar(sessao_db: Session) -> dict[str, Any]:
            colecoes = sessao_db.execute(
                select(Document.collection, func.count(Document.id)).group_by(
                    Document.collection
                )
            ).all()
            return {
                "documents": sessao_db.scalar(select(func.count(Document.id))) or 0,
                "embeddings": sessao_db.scalar(select(func.count(Embedding.id))) or 0,
                "indexed": sessao_db.scalar(
                    select(func.count(Document.id)).where(Document.status == "indexed")
                )
                or 0,
                "failed": sessao_db.scalar(
                    select(func.count(Document.id)).where(Document.status == "failed")
                )
                or 0,
                "collections": {nome: qtd for nome, qtd in colecoes},
                "index_backend": self.store.nome,
                "index_size": self.store.tamanho(),
                "embedder": servico_embeddings.info(),
            }

        if db is not None:
            return coletar(db)
        with sessao() as nova:
            return coletar(nova)


def _checksum(caminho: Path) -> str:
    """SHA-256 do arquivo, lido em blocos para suportar arquivos grandes."""
    digest = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


# Instância única.
pipeline = PipelineRAG()
