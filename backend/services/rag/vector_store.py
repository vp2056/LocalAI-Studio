"""
Índice vetorial com três backends intercambiáveis.

  * ``FaissStore``  – índice FAISS em memória, persistido em disco;
  * ``ChromaStore`` – ChromaDB persistente;
  * ``NumpyStore``  – produto matricial com NumPy (sempre disponível).

Todos os vetores também vivem na tabela ``embeddings``, que é a fonte da
verdade: o índice pode ser reconstruído a qualquer momento com ``reconstruir``.
Isso torna a troca de backend e a recuperação de corrupção operações triviais.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ...config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Resultado:
    """Um trecho recuperado pela busca."""

    embedding_id: int
    score: float
    content: str = ""
    document_id: int | None = None
    document_title: str | None = None
    collection: str = "default"
    meta: dict[str, Any] | None = None


class VectorStore(Protocol):
    """Contrato de um índice vetorial."""

    nome: str

    def adicionar(self, ids: list[int], vetores: np.ndarray) -> None: ...
    def remover(self, ids: list[int]) -> None: ...
    def buscar(self, vetor: np.ndarray, k: int) -> list[tuple[int, float]]: ...
    def limpar(self) -> None: ...
    def salvar(self) -> None: ...
    def tamanho(self) -> int: ...


# ===========================================================================
# NumPy (sempre disponível)
# ===========================================================================
class NumpyStore:
    """
    Busca exata por produto interno.

    Adequado até a casa das centenas de milhares de vetores; acima disso o
    FAISS passa a compensar. Vetores são mantidos normalizados, então o
    produto interno equivale à similaridade cosseno.
    """

    nome = "numpy"

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._ids: list[int] = []
        self._matriz = np.zeros((0, dim), dtype=np.float32)
        self._lock = threading.RLock()

    def adicionar(self, ids: list[int], vetores: np.ndarray) -> None:
        if not ids:
            return
        with self._lock:
            self._ids.extend(ids)
            self._matriz = (
                vetores.astype(np.float32)
                if self._matriz.size == 0
                else np.vstack([self._matriz, vetores.astype(np.float32)])
            )

    def remover(self, ids: list[int]) -> None:
        if not ids:
            return
        alvo = set(ids)
        with self._lock:
            manter = [i for i, eid in enumerate(self._ids) if eid not in alvo]
            self._ids = [self._ids[i] for i in manter]
            self._matriz = (
                self._matriz[manter]
                if manter
                else np.zeros((0, self.dim), dtype=np.float32)
            )

    def buscar(self, vetor: np.ndarray, k: int) -> list[tuple[int, float]]:
        with self._lock:
            if self._matriz.shape[0] == 0:
                return []
            scores = self._matriz @ vetor.astype(np.float32)
            k = min(k, len(scores))
            # argpartition evita ordenar todo o vetor de scores.
            topo = np.argpartition(-scores, k - 1)[:k]
            topo = topo[np.argsort(-scores[topo])]
            return [(self._ids[i], float(scores[i])) for i in topo]

    def limpar(self) -> None:
        with self._lock:
            self._ids.clear()
            self._matriz = np.zeros((0, self.dim), dtype=np.float32)

    def salvar(self) -> None:
        """Sem persistência própria: reconstruído do banco na inicialização."""

    def tamanho(self) -> int:
        return len(self._ids)


# ===========================================================================
# FAISS
# ===========================================================================
class FaissStore:
    """Índice FAISS ``IndexIDMap`` sobre ``IndexFlatIP``."""

    nome = "faiss"

    def __init__(self, dim: int, caminho: Path) -> None:
        import faiss

        self._faiss = faiss
        self.dim = dim
        self._caminho = caminho
        self._lock = threading.RLock()
        # IndexIDMap permite usar os IDs do banco diretamente no índice.
        self._indice = faiss.IndexIDMap(faiss.IndexFlatIP(dim))

        if caminho.exists():
            try:
                self._indice = faiss.read_index(str(caminho))
                logger.info("Índice FAISS carregado (%d vetores).", self.tamanho())
            except Exception as exc:
                logger.warning("Índice FAISS ilegível (%s); será reconstruído.", exc)

    def adicionar(self, ids: list[int], vetores: np.ndarray) -> None:
        if not ids:
            return
        with self._lock:
            self._indice.add_with_ids(
                np.ascontiguousarray(vetores, dtype=np.float32),
                np.asarray(ids, dtype=np.int64),
            )

    def remover(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._indice.remove_ids(np.asarray(ids, dtype=np.int64))

    def buscar(self, vetor: np.ndarray, k: int) -> list[tuple[int, float]]:
        with self._lock:
            if self.tamanho() == 0:
                return []
            consulta = np.ascontiguousarray(
                vetor.reshape(1, -1), dtype=np.float32
            )
            scores, ids = self._indice.search(consulta, min(k, self.tamanho()))
        # FAISS devolve -1 para posições vazias do resultado.
        return [
            (int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1
        ]

    def limpar(self) -> None:
        with self._lock:
            self._indice = self._faiss.IndexIDMap(self._faiss.IndexFlatIP(self.dim))

    def salvar(self) -> None:
        with self._lock:
            self._caminho.parent.mkdir(parents=True, exist_ok=True)
            self._faiss.write_index(self._indice, str(self._caminho))

    def tamanho(self) -> int:
        return int(self._indice.ntotal)


# ===========================================================================
# ChromaDB
# ===========================================================================
class ChromaStore:
    """Coleção ChromaDB persistente."""

    nome = "chroma"

    def __init__(self, dim: int, caminho: Path) -> None:
        import chromadb

        self.dim = dim
        self._cliente = chromadb.PersistentClient(path=str(caminho))
        self._colecao = self._cliente.get_or_create_collection(
            name="localai_studio",
            # Chroma usa distância L2 por padrão; com vetores normalizados,
            # cosseno é a métrica correta.
            metadata={"hnsw:space": "cosine"},
        )

    def adicionar(self, ids: list[int], vetores: np.ndarray) -> None:
        if not ids:
            return
        self._colecao.upsert(
            ids=[str(i) for i in ids], embeddings=vetores.tolist()
        )

    def remover(self, ids: list[int]) -> None:
        if ids:
            self._colecao.delete(ids=[str(i) for i in ids])

    def buscar(self, vetor: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self.tamanho() == 0:
            return []
        saida = self._colecao.query(
            query_embeddings=[vetor.tolist()], n_results=min(k, self.tamanho())
        )
        ids = saida.get("ids", [[]])[0]
        distancias = saida.get("distances", [[]])[0]
        # Converte distância de cosseno (0..2) em similaridade (1..-1).
        return [(int(i), 1.0 - float(d)) for i, d in zip(ids, distancias)]

    def limpar(self) -> None:
        self._cliente.delete_collection("localai_studio")
        self._colecao = self._cliente.get_or_create_collection(
            name="localai_studio", metadata={"hnsw:space": "cosine"}
        )

    def salvar(self) -> None:
        """O PersistentClient grava automaticamente."""

    def tamanho(self) -> int:
        return int(self._colecao.count())


# ===========================================================================
# Fábrica
# ===========================================================================
def criar_store(dim: int) -> VectorStore:
    """Instancia o backend configurado, com degradação para NumPy."""
    preferido = settings.vector_backend.lower()
    diretorio = settings.caminho("database")

    if preferido == "faiss":
        try:
            return FaissStore(dim, diretorio / "faiss.index")
        except ImportError:
            logger.info("faiss não instalado; usando índice NumPy.")
        except Exception:
            logger.exception("Falha ao iniciar FAISS; usando índice NumPy.")

    elif preferido == "chroma":
        try:
            return ChromaStore(dim, diretorio / "chroma")
        except ImportError:
            logger.info("chromadb não instalado; usando índice NumPy.")
        except Exception:
            logger.exception("Falha ao iniciar ChromaDB; usando índice NumPy.")

    return NumpyStore(dim)
