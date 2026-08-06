"""
Implementações concretas dos backends de inferência.

  * ``LlamaCppBackend``     – modelos GGUF via llama-cpp-python (CPU/GPU).
  * ``TransformersBackend`` – modelos HuggingFace (safetensors/bin) via torch.
  * ``OnnxBackend``         – modelos ONNX via onnxruntime.
  * ``EchoBackend``         – backend de diagnóstico, sempre disponível.

Todas as dependências pesadas são importadas sob demanda, dentro de
``carregar()``. Isso mantém a inicialização do servidor rápida e permite que o
sistema suba mesmo sem nenhuma delas instalada.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from importlib.util import find_spec

from ...core.exceptions import BackendIndisponivel
from .base import BackendLLM, InfoModelo, Mensagem, ParametrosGeracao

logger = logging.getLogger(__name__)


def _threads_padrao() -> int:
    """Número de threads de CPU a usar (deixa um núcleo livre para a UI)."""
    from ...config import settings

    if settings.n_threads > 0:
        return settings.n_threads
    return max(1, (os.cpu_count() or 4) - 1)


# ===========================================================================
# llama.cpp — GGUF
# ===========================================================================
class LlamaCppBackend(BackendLLM):
    """Execução de modelos GGUF via llama-cpp-python."""

    nome = "llama_cpp"
    formatos = ("gguf",)

    def __init__(self, info: InfoModelo) -> None:
        super().__init__(info)
        self._llm = None

    @classmethod
    def disponivel(cls) -> bool:
        return find_spec("llama_cpp") is not None

    def carregar(self) -> None:
        if self._carregado:
            return
        if not self.disponivel():
            raise BackendIndisponivel(
                "llama-cpp-python não está instalado. "
                "Execute: pip install llama-cpp-python"
            )

        from llama_cpp import Llama  # import tardio: dependência pesada

        from ...config import settings

        inicio = time.perf_counter()
        logger.info("Carregando modelo GGUF: %s", self.info.name)

        self._llm = Llama(
            model_path=self.info.path,
            n_ctx=self.info.context_length or settings.context_length,
            n_threads=_threads_padrao(),
            n_gpu_layers=settings.n_gpu_layers,
            embedding=True,  # habilita create_embedding no mesmo modelo
            verbose=settings.debug,
        )
        self._carregado = True
        logger.info(
            "Modelo '%s' carregado em %.2fs",
            self.info.name,
            time.perf_counter() - inicio,
        )

    def descarregar(self) -> None:
        if self._llm is not None:
            # llama-cpp libera os buffers nativos no __del__ do objeto.
            self._llm = None
            self._carregado = False
            logger.info("Modelo '%s' descarregado.", self.info.name)

    def gerar(
        self, mensagens: list[Mensagem], params: ParametrosGeracao
    ) -> Iterator[str]:
        self.carregar()
        assert self._llm is not None

        payload = [{"role": m.role, "content": m.content} for m in mensagens]
        try:
            fluxo = self._llm.create_chat_completion(
                messages=payload,
                max_tokens=params.max_tokens,
                temperature=params.temperature,
                top_p=params.top_p,
                top_k=params.top_k,
                repeat_penalty=params.repeat_penalty,
                seed=params.seed if params.seed >= 0 else None,
                stop=params.stop or None,
                stream=True,
            )
            for pedaco in fluxo:
                delta = pedaco["choices"][0].get("delta", {})
                if conteudo := delta.get("content"):
                    yield conteudo
        except Exception as exc:
            # Modelos sem template de chat embutido falham no create_chat_completion;
            # nesse caso caímos para a API de completion textual.
            logger.warning(
                "Chat completion falhou (%s); usando completion simples.", exc
            )
            yield from self._gerar_completion(mensagens, params)

    def _gerar_completion(
        self, mensagens: list[Mensagem], params: ParametrosGeracao
    ) -> Iterator[str]:
        assert self._llm is not None
        fluxo = self._llm.create_completion(
            prompt=self.montar_prompt_simples(mensagens),
            max_tokens=params.max_tokens,
            temperature=params.temperature,
            top_p=params.top_p,
            top_k=params.top_k,
            repeat_penalty=params.repeat_penalty,
            seed=params.seed if params.seed >= 0 else None,
            stop=params.stop or ["Usuário:", "Instruções:"],
            stream=True,
        )
        for pedaco in fluxo:
            if texto := pedaco["choices"][0].get("text"):
                yield texto

    def contar_tokens(self, texto: str) -> int:
        if self._llm is None:
            return super().contar_tokens(texto)
        try:
            return len(self._llm.tokenize(texto.encode("utf-8")))
        except Exception:
            return super().contar_tokens(texto)

    def embeddings(self, textos: list[str]) -> list[list[float]]:
        self.carregar()
        assert self._llm is not None
        resultado = []
        for texto in textos:
            saida = self._llm.create_embedding(texto)
            resultado.append(saida["data"][0]["embedding"])
        return resultado


# ===========================================================================
# Transformers — safetensors / bin
# ===========================================================================
class TransformersBackend(BackendLLM):
    """Execução de modelos HuggingFace locais (safetensors, bin)."""

    nome = "transformers"
    formatos = ("safetensors", "transformers", "bin")

    def __init__(self, info: InfoModelo) -> None:
        super().__init__(info)
        self._modelo = None
        self._tokenizador = None
        self._dispositivo = "cpu"

    @classmethod
    def disponivel(cls) -> bool:
        return find_spec("transformers") is not None and find_spec("torch") is not None

    def carregar(self) -> None:
        if self._carregado:
            return
        if not self.disponivel():
            raise BackendIndisponivel(
                "transformers/torch não estão instalados. "
                "Execute: pip install transformers torch"
            )

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        inicio = time.perf_counter()
        logger.info("Carregando modelo Transformers: %s", self.info.name)

        self._dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
        # float16 na GPU reduz pela metade o uso de VRAM; na CPU float32 é
        # mais rápido e evita operações não suportadas.
        dtype = torch.float16 if self._dispositivo == "cuda" else torch.float32

        self._tokenizador = AutoTokenizer.from_pretrained(
            self.info.path, local_files_only=True
        )
        self._modelo = AutoModelForCausalLM.from_pretrained(
            self.info.path, torch_dtype=dtype, local_files_only=True
        ).to(self._dispositivo)
        self._modelo.eval()

        self._carregado = True
        logger.info(
            "Modelo '%s' carregado em %s (%.2fs)",
            self.info.name,
            self._dispositivo,
            time.perf_counter() - inicio,
        )

    def descarregar(self) -> None:
        if self._modelo is None:
            return
        self._modelo = None
        self._tokenizador = None
        self._carregado = False
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("Modelo '%s' descarregado.", self.info.name)

    def gerar(
        self, mensagens: list[Mensagem], params: ParametrosGeracao
    ) -> Iterator[str]:
        self.carregar()
        import threading

        import torch
        from transformers import TextIteratorStreamer

        tok = self._tokenizador
        assert tok is not None and self._modelo is not None

        prompt = self._montar_prompt(mensagens)
        entradas = tok(prompt, return_tensors="pt").to(self._dispositivo)

        streamer = TextIteratorStreamer(
            tok, skip_prompt=True, skip_special_tokens=True
        )
        if params.seed >= 0:
            torch.manual_seed(params.seed)

        argumentos = dict(
            **entradas,
            max_new_tokens=params.max_tokens,
            temperature=max(params.temperature, 1e-4),
            top_p=params.top_p,
            top_k=params.top_k,
            repetition_penalty=params.repeat_penalty,
            do_sample=params.temperature > 0,
            pad_token_id=tok.pad_token_id or tok.eos_token_id,
            streamer=streamer,
        )

        # A geração roda em thread separada porque o streamer é um iterador
        # bloqueante alimentado pelo laço de generate().
        thread = threading.Thread(
            target=self._modelo.generate, kwargs=argumentos, daemon=True
        )
        thread.start()

        for texto in streamer:
            if texto:
                yield texto
        thread.join(timeout=1)

    def _montar_prompt(self, mensagens: list[Mensagem]) -> str:
        """Usa o chat template do tokenizador quando o modelo define um."""
        tok = self._tokenizador
        payload = [{"role": m.role, "content": m.content} for m in mensagens]
        if getattr(tok, "chat_template", None):
            try:
                return tok.apply_chat_template(
                    payload, tokenize=False, add_generation_prompt=True
                )
            except Exception:
                pass
        return self.montar_prompt_simples(mensagens)

    def contar_tokens(self, texto: str) -> int:
        if self._tokenizador is None:
            return super().contar_tokens(texto)
        return len(self._tokenizador.encode(texto))


# ===========================================================================
# ONNX Runtime
# ===========================================================================
class OnnxBackend(BackendLLM):
    """
    Execução de modelos ONNX.

    Voltado a modelos de embedding e classificação exportados para ONNX; a
    geração autorregressiva exige um pipeline específico (optimum), portanto
    delega ao ``optimum.onnxruntime`` quando disponível.
    """

    nome = "onnx"
    formatos = ("onnx",)

    def __init__(self, info: InfoModelo) -> None:
        super().__init__(info)
        self._sessao = None
        self._pipeline = None

    @classmethod
    def disponivel(cls) -> bool:
        return find_spec("onnxruntime") is not None

    def carregar(self) -> None:
        if self._carregado:
            return
        if not self.disponivel():
            raise BackendIndisponivel(
                "onnxruntime não está instalado. Execute: pip install onnxruntime"
            )

        import onnxruntime as ort

        provedores = ort.get_available_providers()
        # Prioriza GPU quando o provider estiver presente.
        escolhidos = [
            p
            for p in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
            if p in provedores
        ]
        self._sessao = ort.InferenceSession(self.info.path, providers=escolhidos)
        self._carregado = True
        logger.info(
            "Sessão ONNX criada para '%s' (providers=%s)", self.info.name, escolhidos
        )

    def descarregar(self) -> None:
        self._sessao = None
        self._pipeline = None
        self._carregado = False

    def gerar(
        self, mensagens: list[Mensagem], params: ParametrosGeracao
    ) -> Iterator[str]:
        if find_spec("optimum") is None:
            raise BackendIndisponivel(
                "Geração de texto com ONNX requer 'optimum'. "
                "Execute: pip install optimum[onnxruntime]"
            )

        from optimum.onnxruntime import ORTModelForCausalLM
        from transformers import AutoTokenizer, pipeline

        if self._pipeline is None:
            diretorio = os.path.dirname(self.info.path)
            modelo = ORTModelForCausalLM.from_pretrained(diretorio, local_files_only=True)
            tok = AutoTokenizer.from_pretrained(diretorio, local_files_only=True)
            self._pipeline = pipeline("text-generation", model=modelo, tokenizer=tok)
            self._carregado = True

        saida = self._pipeline(
            self.montar_prompt_simples(mensagens),
            max_new_tokens=params.max_tokens,
            temperature=max(params.temperature, 1e-4),
            top_p=params.top_p,
            do_sample=params.temperature > 0,
            return_full_text=False,
        )
        # O pipeline não é incremental: entregamos em blocos para preservar a
        # sensação de streaming na interface.
        texto = saida[0]["generated_text"]
        for i in range(0, len(texto), 24):
            yield texto[i : i + 24]


# ===========================================================================
# Echo — diagnóstico
# ===========================================================================
class EchoBackend(BackendLLM):
    """
    Backend sem IA, sempre disponível.

    Permite validar toda a cadeia (interface → WebSocket → banco → histórico)
    antes de instalar qualquer modelo, e serve de diagnóstico quando o usuário
    relata que "o chat não responde".
    """

    nome = "echo"
    formatos = ("echo",)

    @classmethod
    def disponivel(cls) -> bool:
        return True

    def carregar(self) -> None:
        self._carregado = True

    def descarregar(self) -> None:
        self._carregado = False

    def gerar(
        self, mensagens: list[Mensagem], params: ParametrosGeracao
    ) -> Iterator[str]:
        ultima = next(
            (m.content for m in reversed(mensagens) if m.role == "user"), ""
        )
        resposta = (
            "**Modo diagnóstico** — nenhum modelo de IA está carregado.\n\n"
            f"Sua mensagem tinha {len(ultima)} caracteres "
            f"(~{self.contar_tokens(ultima)} tokens).\n\n"
            "Para conversar de verdade:\n"
            "1. Vá em **Modelos**;\n"
            "2. Importe um arquivo `.gguf` ou aponte uma pasta de modelo;\n"
            "3. Instale o motor: `pip install llama-cpp-python`;\n"
            "4. Selecione o modelo no seletor acima do chat.\n\n"
            f"Parâmetros ativos: temperatura={params.temperature}, "
            f"top_p={params.top_p}, top_k={params.top_k}, "
            f"max_tokens={params.max_tokens}."
        )
        # Emite palavra a palavra para exercitar o caminho de streaming.
        for palavra in resposta.split(" "):
            yield palavra + " "


# Registro de backends conhecidos, na ordem de preferência para cada formato.
BACKENDS: dict[str, type[BackendLLM]] = {
    LlamaCppBackend.nome: LlamaCppBackend,
    TransformersBackend.nome: TransformersBackend,
    OnnxBackend.nome: OnnxBackend,
    EchoBackend.nome: EchoBackend,
}


def backend_para_formato(formato: str) -> type[BackendLLM]:
    """Escolhe a classe de backend adequada a um formato de arquivo."""
    for classe in (LlamaCppBackend, TransformersBackend, OnnxBackend):
        if formato in classe.formatos:
            return classe
    return EchoBackend


def backends_disponiveis() -> dict[str, bool]:
    """Mapa ``nome -> instalado`` para exibição no painel do sistema."""
    return {nome: classe.disponivel() for nome, classe in BACKENDS.items()}
