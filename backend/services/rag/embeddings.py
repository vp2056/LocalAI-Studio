"""
Geração de embeddings.

Ordem de preferência:
  1. ``sentence-transformers`` com o modelo configurado (qualidade real);
  2. modelo GGUF de embedding carregado pelo gerenciador (llama.cpp);
  3. ``HashingEmbedder`` — projeção determinística de n-gramas, sem dependências.

O fallback (3) mantém a busca funcional offline e sem downloads: usa hashing
de n-gramas de caracteres, o que captura similaridade lexical (bom para nomes,
códigos e termos exatos), embora não capture sinonímia. O sistema avisa na
interface quando está operando nesse modo.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Protocol

import numpy as np

from ...config import settings

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Contrato mínimo de um gerador de embeddings."""

    nome: str
    dim: int
    semantico: bool

    def codificar(self, textos: list[str]) -> np.ndarray:
        """Devolve uma matriz (n, dim) de vetores normalizados."""
        ...


# ===========================================================================
# Fallback determinístico
# ===========================================================================
class HashingEmbedder:
    """
    Embedding por hashing de n-gramas de caracteres.

    Determinístico, instantâneo e sem dependências. Serve de base para a busca
    lexical quando nenhum modelo de embedding está instalado.
    """

    nome = "hashing-ngram"
    semantico = False

    def __init__(self, dim: int = 384, n: tuple[int, ...] = (3, 4, 5)) -> None:
        self.dim = dim
        self._n = n

    def codificar(self, textos: list[str]) -> np.ndarray:
        matriz = np.zeros((len(textos), self.dim), dtype=np.float32)

        for linha, texto in enumerate(textos):
            normalizado = self._normalizar(texto)
            if not normalizado:
                continue

            for token in self._tokens(normalizado):
                indice = (
                    int.from_bytes(
                        hashlib.blake2b(token.encode(), digest_size=4).digest(),
                        "little",
                    )
                    % self.dim
                )
                # Sinal alternado reduz colisões construtivas espúrias.
                matriz[linha, indice] += 1.0 if indice % 2 == 0 else -1.0

        return normalizar(matriz)

    def _tokens(self, texto: str):
        """
        Produz os tokens que compõem o vetor.

        Além dos n-gramas de caracteres, emitimos as palavras inteiras: textos
        muito curtos ("um", "ok") não têm n-gramas do tamanho configurado e
        gerariam um vetor nulo, que nunca casaria com consulta alguma.
        """
        for palavra in texto.split():
            yield palavra

        for tamanho in self._n:
            for i in range(len(texto) - tamanho + 1):
                yield texto[i : i + tamanho]

    @staticmethod
    def _normalizar(texto: str) -> str:
        return re.sub(r"\s+", " ", texto.lower()).strip()


# ===========================================================================
# sentence-transformers
# ===========================================================================
class SentenceTransformerEmbedder:
    """Embeddings semânticos de verdade via sentence-transformers."""

    semantico = True

    def __init__(self, nome_modelo: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.nome = nome_modelo
        # local_files_only evita qualquer tentativa de rede (requisito offline).
        try:
            self._modelo = SentenceTransformer(nome_modelo, local_files_only=True)
        except TypeError:
            # Versões antigas não aceitam o parâmetro; tentamos sem ele.
            self._modelo = SentenceTransformer(nome_modelo)
        self.dim = int(self._modelo.get_sentence_embedding_dimension())

    def codificar(self, textos: list[str]) -> np.ndarray:
        vetores = self._modelo.encode(
            textos,
            batch_size=32,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vetores, dtype=np.float32)


# ===========================================================================
# llama.cpp (modelo GGUF de embedding)
# ===========================================================================
class LlamaEmbedder:
    """Usa um modelo GGUF carregado pelo gerenciador para gerar embeddings."""

    semantico = True

    def __init__(self, nome_modelo: str) -> None:
        from ..llm.manager import gerenciador

        self.nome = nome_modelo
        self._backend = gerenciador.carregar(nome_modelo)
        amostra = self._backend.embeddings(["dimensão"])
        self.dim = len(amostra[0])

    def codificar(self, textos: list[str]) -> np.ndarray:
        vetores = self._backend.embeddings(textos)
        return normalizar(np.asarray(vetores, dtype=np.float32))


# ===========================================================================
# Serviço
# ===========================================================================
class ServicoEmbeddings:
    """Fachada única de embeddings, com seleção automática do provedor."""

    def __init__(self) -> None:
        self._embedder: Embedder | None = None
        self._lock = threading.Lock()

    @property
    def embedder(self) -> Embedder:
        """Instancia o melhor provedor disponível (uma única vez)."""
        if self._embedder is not None:
            return self._embedder

        with self._lock:
            if self._embedder is not None:
                return self._embedder
            self._embedder = self._escolher()
            logger.info(
                "Embeddings: provedor '%s' (dim=%d, semântico=%s)",
                self._embedder.nome,
                self._embedder.dim,
                self._embedder.semantico,
            )
            return self._embedder

    def _escolher(self) -> Embedder:
        alvo = settings.embedding_model

        try:
            return SentenceTransformerEmbedder(alvo)
        except Exception as exc:
            logger.info("sentence-transformers indisponível (%s).", exc)

        # Procura um modelo local marcado como de embedding.
        try:
            from ..llm.manager import gerenciador

            candidatos = [
                m for m in gerenciador.listar() if m.kind == "embedding"
            ]
            if candidatos:
                return LlamaEmbedder(candidatos[0].name)
        except Exception as exc:
            logger.info("Nenhum modelo GGUF de embedding utilizável (%s).", exc)

        logger.warning(
            "Usando embeddings por hashing (busca lexical). Para busca "
            "semântica, instale: pip install sentence-transformers"
        )
        return HashingEmbedder(dim=settings.embedding_dim)

    # ---------------------------------------------------------------- API
    def codificar(self, textos: list[str]) -> np.ndarray:
        """Vetoriza uma lista de textos."""
        if not textos:
            return np.zeros((0, self.dim), dtype=np.float32)
        return self.embedder.codificar(textos)

    def codificar_um(self, texto: str) -> np.ndarray:
        """Vetoriza um único texto, devolvendo um vetor 1-D."""
        return self.codificar([texto])[0]

    @property
    def dim(self) -> int:
        return self.embedder.dim

    @property
    def nome(self) -> str:
        return self.embedder.nome

    @property
    def semantico(self) -> bool:
        """Indica se o provedor atual captura significado (e não só léxico)."""
        return self.embedder.semantico

    def info(self) -> dict:
        return {
            "provider": self.nome,
            "dimension": self.dim,
            "semantic": self.semantico,
            "configured_model": settings.embedding_model,
        }


def normalizar(matriz: np.ndarray) -> np.ndarray:
    """Normaliza cada linha para norma 1 (produto interno = similaridade cosseno)."""
    if matriz.ndim == 1:
        matriz = matriz.reshape(1, -1)
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    # Evita divisão por zero em vetores nulos (texto sem n-gramas úteis).
    normas[normas == 0] = 1.0
    return (matriz / normas).astype(np.float32)


# Instância única.
servico_embeddings = ServicoEmbeddings()
