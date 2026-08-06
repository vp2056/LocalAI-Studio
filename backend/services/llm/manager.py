"""
Gerenciador de modelos.

Responsabilidades:
  * varrer a pasta ``models/`` e registrar o que encontrar no banco;
  * extrair metadados técnicos (GGUF, config.json);
  * carregar/descarregar backends respeitando ``max_loaded_models`` (LRU);
  * expor uma API única de geração para as rotas HTTP e o WebSocket.

Instância única exportada como ``gerenciador``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...config import settings
from ...core.exceptions import ModeloNaoEncontrado
from ...database.models import AIModel
from ...database.session import sessao
from . import gguf
from .backends import BACKENDS, EchoBackend, backend_para_formato, backends_disponiveis
from .base import BackendLLM, InfoModelo, Mensagem, ParametrosGeracao

logger = logging.getLogger(__name__)

# Nome reservado do backend de diagnóstico usado quando não há modelo real.
MODELO_DIAGNOSTICO = "diagnóstico"

# Arquivos que identificam um diretório como modelo HuggingFace.
MARCADORES_HF = ("config.json", "model.safetensors.index.json")


class GerenciadorModelos:
    """Ciclo de vida dos modelos de IA."""

    def __init__(self) -> None:
        # OrderedDict usado como cache LRU: o primeiro item é o menos recente.
        self._carregados: OrderedDict[str, BackendLLM] = OrderedDict()
        self._lock = threading.RLock()

    # ------------------------------------------------------------ descoberta
    def escanear(self, registrar: bool = True) -> list[InfoModelo]:
        """
        Percorre ``models/`` em busca de modelos e sincroniza com o banco.

        Marca como indisponíveis os registros cujo arquivo sumiu, em vez de
        apagá-los — o histórico de conversas continua referenciando o nome.
        """
        raiz = settings.caminho("models")
        encontrados: list[InfoModelo] = []
        vistos: set[str] = set()

        # 1) Arquivos soltos (GGUF, ONNX).
        for arquivo in sorted(raiz.rglob("*")):
            if not arquivo.is_file():
                continue
            sufixo = arquivo.suffix.lower()
            if sufixo == ".gguf":
                encontrados.append(self._info_gguf(arquivo))
            elif sufixo == ".onnx":
                encontrados.append(self._info_onnx(arquivo))

        # 2) Diretórios no formato HuggingFace.
        for diretorio in sorted(p for p in raiz.rglob("*") if p.is_dir()):
            if any((diretorio / marcador).exists() for marcador in MARCADORES_HF):
                encontrados.append(self._info_hf(diretorio))

        for info in encontrados:
            vistos.add(info.path)

        if registrar:
            self._sincronizar_banco(encontrados, vistos)

        logger.info("Varredura de modelos: %d encontrado(s).", len(encontrados))
        return encontrados

    def _info_gguf(self, arquivo: Path) -> InfoModelo:
        meta = gguf.ler_metadados(arquivo)
        return InfoModelo(
            name=arquivo.stem,
            path=str(arquivo),
            format="gguf",
            backend="llama_cpp",
            size_bytes=arquivo.stat().st_size,
            context_length=int(meta.get("context_length") or settings.context_length),
            quantization=str(meta.get("quantization") or "") or None,
            parameters=meta.get("parameters_human"),
            architecture=meta.get("architecture"),
            kind="chat",
            meta=meta,
        )

    def _info_onnx(self, arquivo: Path) -> InfoModelo:
        return InfoModelo(
            name=arquivo.stem,
            path=str(arquivo),
            format="onnx",
            backend="onnx",
            size_bytes=arquivo.stat().st_size,
            context_length=settings.context_length,
            kind="chat",
            meta={},
        )

    def _info_hf(self, diretorio: Path) -> InfoModelo:
        config: dict[str, Any] = {}
        arquivo_config = diretorio / "config.json"
        if arquivo_config.exists():
            try:
                config = json.loads(arquivo_config.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("config.json inválido em %s: %s", diretorio, exc)

        tamanho = sum(f.stat().st_size for f in diretorio.rglob("*") if f.is_file())
        # Modelos de embedding declaram arquitetura BERT-like sem cabeça causal.
        arquiteturas = config.get("architectures") or []
        eh_embedding = any("Model" == a[-5:] for a in arquiteturas) and not any(
            "CausalLM" in a for a in arquiteturas
        )

        return InfoModelo(
            name=diretorio.name,
            path=str(diretorio),
            format="safetensors",
            backend="transformers",
            size_bytes=tamanho,
            context_length=int(
                config.get("max_position_embeddings") or settings.context_length
            ),
            architecture=config.get("model_type"),
            parameters=None,
            kind="embedding" if eh_embedding else "chat",
            meta={"config": {k: config.get(k) for k in (
                "model_type", "hidden_size", "num_hidden_layers",
                "num_attention_heads", "vocab_size", "torch_dtype",
            ) if k in config}},
        )

    def _sincronizar_banco(self, encontrados: list[InfoModelo], vistos: set[str]) -> None:
        """Insere/atualiza registros e marca ausentes como indisponíveis."""
        with sessao() as db:
            existentes = {m.path: m for m in db.query(AIModel).all()}

            for info in encontrados:
                registro = existentes.get(info.path)
                if registro is None:
                    db.add(
                        AIModel(
                            name=info.name,
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
                            is_available=True,
                        )
                    )
                else:
                    registro.size_bytes = info.size_bytes
                    registro.context_length = info.context_length
                    registro.quantization = info.quantization or registro.quantization
                    registro.architecture = info.architecture or registro.architecture
                    registro.parameters = info.parameters or registro.parameters
                    registro.meta = info.meta or registro.meta
                    registro.is_available = True

            for caminho, registro in existentes.items():
                if caminho not in vistos and registro.is_available:
                    registro.is_available = False
                    logger.warning("Modelo ausente do disco: %s", registro.name)

    # -------------------------------------------------------------- consulta
    def listar(self, apenas_disponiveis: bool = True) -> list[AIModel]:
        """Lista os modelos registrados."""
        with sessao() as db:
            consulta = db.query(AIModel)
            if apenas_disponiveis:
                consulta = consulta.filter(AIModel.is_available.is_(True))
            return consulta.order_by(AIModel.name).all()

    def obter(self, nome: str) -> AIModel | None:
        with sessao() as db:
            return db.query(AIModel).filter(AIModel.name == nome).first()

    def modelo_padrao(self) -> str | None:
        """Nome do modelo a usar quando a requisição não especifica um."""
        if settings.default_model:
            return settings.default_model
        with sessao() as db:
            marcado = (
                db.query(AIModel)
                .filter(AIModel.is_default.is_(True), AIModel.is_available.is_(True))
                .first()
            )
            if marcado:
                return marcado.name
            # Sem padrão explícito: o modelo de chat mais usado.
            primeiro = (
                db.query(AIModel)
                .filter(AIModel.is_available.is_(True), AIModel.kind == "chat")
                .order_by(AIModel.usage_count.desc(), AIModel.name)
                .first()
            )
            return primeiro.name if primeiro else None

    # ---------------------------------------------------- carga / descarga
    def carregar(self, nome: str | None) -> BackendLLM:
        """
        Devolve o backend pronto para uso do modelo indicado.

        Sem nome (ou sem modelos instalados), cai para o backend de
        diagnóstico, que sempre responde.
        """
        nome = nome or self.modelo_padrao()
        if not nome:
            return self._backend_diagnostico()

        with self._lock:
            if nome in self._carregados:
                self._carregados.move_to_end(nome)
                return self._carregados[nome]

        registro = self.obter(nome)
        if registro is None:
            raise ModeloNaoEncontrado(f"Modelo '{nome}' não está registrado.")
        if not registro.is_available:
            raise ModeloNaoEncontrado(
                f"O arquivo do modelo '{nome}' não foi encontrado no disco."
            )

        info = InfoModelo(
            name=registro.name,
            path=registro.path,
            format=registro.format,
            backend=registro.backend,
            size_bytes=registro.size_bytes,
            context_length=registro.context_length,
            quantization=registro.quantization,
            parameters=registro.parameters,
            architecture=registro.architecture,
            kind=registro.kind,
            meta=registro.meta or {},
        )

        classe = BACKENDS.get(registro.backend) or backend_para_formato(registro.format)
        backend = classe(info)

        with self._lock:
            self._liberar_espaco()
            backend.carregar()
            self._carregados[nome] = backend

        self._registrar_uso(nome)
        return backend

    def _liberar_espaco(self) -> None:
        """Descarrega os modelos menos usados até respeitar o limite."""
        while len(self._carregados) >= max(1, settings.max_loaded_models):
            nome_antigo, backend_antigo = self._carregados.popitem(last=False)
            logger.info("Descarregando '%s' para liberar memória.", nome_antigo)
            try:
                backend_antigo.descarregar()
            except Exception:
                logger.exception("Falha ao descarregar '%s'", nome_antigo)

    def descarregar(self, nome: str) -> bool:
        """Descarrega um modelo específico da memória."""
        with self._lock:
            backend = self._carregados.pop(nome, None)
        if backend is None:
            return False
        backend.descarregar()
        return True

    def descarregar_todos(self) -> None:
        with self._lock:
            nomes = list(self._carregados)
        for nome in nomes:
            self.descarregar(nome)

    def _backend_diagnostico(self) -> BackendLLM:
        with self._lock:
            backend = self._carregados.get(MODELO_DIAGNOSTICO)
            if backend is None:
                backend = EchoBackend(
                    InfoModelo(
                        name=MODELO_DIAGNOSTICO,
                        path="",
                        format="echo",
                        backend="echo",
                    )
                )
                backend.carregar()
                self._carregados[MODELO_DIAGNOSTICO] = backend
            return backend

    def _registrar_uso(self, nome: str) -> None:
        with sessao() as db:
            registro = db.query(AIModel).filter(AIModel.name == nome).first()
            if registro:
                registro.usage_count += 1
                from ...database.base import agora

                registro.last_used_at = agora()

    # -------------------------------------------------------------- geração
    def gerar(
        self,
        mensagens: list[Mensagem],
        *,
        modelo: str | None = None,
        params: ParametrosGeracao | None = None,
    ) -> Iterator[str]:
        """Gera resposta em streaming usando o modelo indicado."""
        backend = self.carregar(modelo)
        yield from backend.gerar(mensagens, params or ParametrosGeracao())

    def gerar_completo(
        self,
        mensagens: list[Mensagem],
        *,
        modelo: str | None = None,
        params: ParametrosGeracao | None = None,
    ) -> dict[str, Any]:
        """Versão não-streaming: acumula a resposta e mede o desempenho."""
        backend = self.carregar(modelo)
        parametros = params or ParametrosGeracao()

        inicio = time.perf_counter()
        partes: list[str] = []
        for pedaco in backend.gerar(mensagens, parametros):
            partes.append(pedaco)
        texto = "".join(partes)
        duracao = time.perf_counter() - inicio

        tokens = backend.contar_tokens(texto)
        return {
            "content": texto,
            "model": backend.info.name,
            "tokens": tokens,
            "duration_ms": int(duracao * 1000),
            "tokens_per_second": round(tokens / duracao, 2) if duracao > 0 else 0.0,
        }

    # ------------------------------------------------------------- estado
    def estado(self) -> dict[str, Any]:
        """Situação atual do gerenciador, para o painel do sistema."""
        with self._lock:
            carregados = [
                {
                    "name": nome,
                    "backend": backend.nome,
                    "format": backend.info.format,
                    "context_length": backend.info.context_length,
                    "size_bytes": backend.info.size_bytes,
                }
                for nome, backend in self._carregados.items()
            ]
        return {
            "loaded": carregados,
            "max_loaded": settings.max_loaded_models,
            "backends": backends_disponiveis(),
            "default_model": self.modelo_padrao(),
        }


# Instância única compartilhada pela aplicação.
gerenciador = GerenciadorModelos()
