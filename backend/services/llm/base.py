"""
Contrato comum dos backends de inferência.

Todo backend implementa ``carregar``, ``gerar`` (streaming) e ``descarregar``.
A camada superior (``manager``) nunca depende de detalhes de llama.cpp,
Transformers ou ONNX — apenas desta interface.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ...config import settings


@dataclass(slots=True)
class ParametrosGeracao:
    """Parâmetros de amostragem de uma geração."""

    max_tokens: int = field(default_factory=lambda: settings.max_tokens)
    temperature: float = field(default_factory=lambda: settings.temperature)
    top_p: float = field(default_factory=lambda: settings.top_p)
    top_k: int = field(default_factory=lambda: settings.top_k)
    repeat_penalty: float = field(default_factory=lambda: settings.repeat_penalty)
    seed: int = field(default_factory=lambda: settings.seed)
    stop: list[str] = field(default_factory=list)

    @classmethod
    def de_dict(cls, dados: dict[str, Any] | None) -> "ParametrosGeracao":
        """Cria a partir de um dict, ignorando chaves desconhecidas e nulas."""
        if not dados:
            return cls()
        validos = {f for f in cls.__slots__}
        return cls(**{k: v for k, v in dados.items() if k in validos and v is not None})

    def para_dict(self) -> dict[str, Any]:
        return {campo: getattr(self, campo) for campo in self.__slots__}


@dataclass(slots=True)
class Mensagem:
    """Mensagem no formato de chat."""

    role: str
    content: str


@dataclass(slots=True)
class InfoModelo:
    """Metadados técnicos lidos do arquivo do modelo."""

    name: str
    path: str
    format: str
    backend: str
    size_bytes: int = 0
    context_length: int = 4096
    quantization: str | None = None
    parameters: str | None = None
    architecture: str | None = None
    kind: str = "chat"
    meta: dict[str, Any] = field(default_factory=dict)


class BackendLLM(abc.ABC):
    """Interface de um backend de inferência."""

    nome: str = "base"
    # Formatos de arquivo que este backend sabe executar.
    formatos: tuple[str, ...] = ()

    def __init__(self, info: InfoModelo) -> None:
        self.info = info
        self._carregado = False

    # -------------------------------------------------------- ciclo de vida
    @classmethod
    @abc.abstractmethod
    def disponivel(cls) -> bool:
        """Indica se as dependências deste backend estão instaladas."""

    @abc.abstractmethod
    def carregar(self) -> None:
        """Carrega o modelo em memória. Deve ser idempotente."""

    @abc.abstractmethod
    def descarregar(self) -> None:
        """Libera a memória ocupada pelo modelo."""

    @property
    def carregado(self) -> bool:
        return self._carregado

    # ------------------------------------------------------------- geração
    @abc.abstractmethod
    def gerar(
        self,
        mensagens: list[Mensagem],
        params: ParametrosGeracao,
    ) -> Iterator[str]:
        """
        Gera a resposta token a token.

        Deve produzir fragmentos de texto (não tokens brutos) para consumo
        direto pelo streaming da API.
        """

    def contar_tokens(self, texto: str) -> int:
        """
        Conta tokens do texto.

        Estimativa padrão de ~4 caracteres por token; backends com tokenizador
        real sobrescrevem este método.
        """
        return max(1, len(texto) // 4)

    def embeddings(self, textos: list[str]) -> list[list[float]]:
        """Gera embeddings. Nem todo backend oferece suporte."""
        raise NotImplementedError(
            f"O backend '{self.nome}' não gera embeddings."
        )

    # ------------------------------------------------------------ auxiliar
    @staticmethod
    def montar_prompt_simples(mensagens: list[Mensagem]) -> str:
        """
        Converte o histórico em um prompt textual genérico.

        Usado por backends sem template de chat próprio.
        """
        rotulos = {
            "system": "Instruções",
            "user": "Usuário",
            "assistant": "Assistente",
            "tool": "Ferramenta",
        }
        partes = [
            f"{rotulos.get(m.role, m.role)}: {m.content}" for m in mensagens if m.content
        ]
        partes.append("Assistente:")
        return "\n\n".join(partes)
