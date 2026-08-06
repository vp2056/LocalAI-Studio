"""
Leitor de metadados GGUF.

Lê apenas o cabeçalho do arquivo (poucos KB), sem carregar os pesos — permite
exibir arquitetura, quantização, contagem de parâmetros e tamanho de contexto
de modelos de dezenas de gigabytes instantaneamente.

Referência do formato: cabeçalho "GGUF" + versão + nº de tensores + nº de
pares de metadados, seguidos dos pares chave/valor tipados.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Any, BinaryIO

logger = logging.getLogger(__name__)

MAGIC = b"GGUF"

# Códigos de tipo dos valores de metadados no GGUF.
(
    T_UINT8, T_INT8, T_UINT16, T_INT16, T_UINT32, T_INT32,
    T_FLOAT32, T_BOOL, T_STRING, T_ARRAY, T_UINT64, T_INT64, T_FLOAT64,
) = range(13)

_FORMATOS_SIMPLES: dict[int, tuple[str, int]] = {
    T_UINT8: ("<B", 1),
    T_INT8: ("<b", 1),
    T_UINT16: ("<H", 2),
    T_INT16: ("<h", 2),
    T_UINT32: ("<I", 4),
    T_INT32: ("<i", 4),
    T_FLOAT32: ("<f", 4),
    T_BOOL: ("<?", 1),
    T_UINT64: ("<Q", 8),
    T_INT64: ("<q", 8),
    T_FLOAT64: ("<d", 8),
}

# Tipos de quantização mais comuns (índice usado no campo ggml_type).
TIPOS_QUANT = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1",
    8: "Q8_0", 9: "Q8_1", 10: "Q2_K", 11: "Q3_K", 12: "Q4_K", 13: "Q5_K",
    14: "Q6_K", 15: "Q8_K", 16: "IQ2_XXS", 17: "IQ2_XS", 18: "IQ3_XXS",
    19: "IQ1_S", 20: "IQ4_NL", 21: "IQ3_S", 22: "IQ2_S", 23: "IQ4_XS",
    24: "IQ1_M", 25: "BF16",
}

# Limite defensivo: cabeçalhos legítimos têm poucos milhares de entradas.
_MAX_ITENS = 1_000_000


def _ler(f: BinaryIO, formato: str, tamanho: int) -> Any:
    dados = f.read(tamanho)
    if len(dados) != tamanho:
        raise ValueError("Arquivo GGUF truncado.")
    return struct.unpack(formato, dados)[0]


def _ler_string(f: BinaryIO) -> str:
    tamanho = _ler(f, "<Q", 8)
    if tamanho > 10_000_000:
        raise ValueError("String de metadado inverossímil no GGUF.")
    return f.read(tamanho).decode("utf-8", errors="replace")


def _ler_valor(f: BinaryIO, tipo: int) -> Any:
    if tipo in _FORMATOS_SIMPLES:
        formato, tamanho = _FORMATOS_SIMPLES[tipo]
        return _ler(f, formato, tamanho)
    if tipo == T_STRING:
        return _ler_string(f)
    if tipo == T_ARRAY:
        tipo_item = _ler(f, "<I", 4)
        quantidade = _ler(f, "<Q", 8)
        if quantidade > _MAX_ITENS:
            raise ValueError("Array de metadado grande demais no GGUF.")
        # Arrays enormes (vocabulário) não interessam: guardamos só o tamanho.
        if quantidade > 64:
            _pular_array(f, tipo_item, quantidade)
            return f"<array[{quantidade}]>"
        return [_ler_valor(f, tipo_item) for _ in range(quantidade)]
    raise ValueError(f"Tipo de metadado GGUF desconhecido: {tipo}")


def _pular_array(f: BinaryIO, tipo_item: int, quantidade: int) -> None:
    """Avança o cursor sobre um array sem materializá-lo em memória."""
    if tipo_item in _FORMATOS_SIMPLES:
        f.seek(_FORMATOS_SIMPLES[tipo_item][1] * quantidade, 1)
        return
    for _ in range(quantidade):
        _ler_valor(f, tipo_item)


def ler_metadados(caminho: str | Path) -> dict[str, Any]:
    """
    Extrai os metadados do cabeçalho de um arquivo GGUF.

    Retorna dict vazio se o arquivo não for GGUF válido — nunca lança para o
    chamador, pois é usado durante a varredura em massa da pasta de modelos.
    """
    caminho = Path(caminho)
    try:
        with caminho.open("rb") as f:
            if f.read(4) != MAGIC:
                return {}
            versao = _ler(f, "<I", 4)
            n_tensores = _ler(f, "<Q", 8)
            n_kv = _ler(f, "<Q", 8)

            if n_kv > _MAX_ITENS:
                return {}

            kv: dict[str, Any] = {}
            for _ in range(n_kv):
                chave = _ler_string(f)
                tipo = _ler(f, "<I", 4)
                kv[chave] = _ler_valor(f, tipo)

            # Descobre a quantização predominante lendo o tipo do 1º tensor.
            quantizacao = _detectar_quantizacao(f, n_tensores)

        return _normalizar(kv, versao, n_tensores, quantizacao, caminho)
    except Exception as exc:
        logger.debug("Falha ao ler metadados GGUF de %s: %s", caminho, exc)
        return {}


def _detectar_quantizacao(f: BinaryIO, n_tensores: int) -> str | None:
    """Lê o tipo ggml do primeiro tensor não trivial do arquivo."""
    if n_tensores == 0:
        return None
    try:
        for _ in range(min(n_tensores, 8)):
            nome = _ler_string(f)
            n_dims = _ler(f, "<I", 4)
            f.seek(8 * n_dims, 1)  # dimensões (uint64 cada)
            tipo = _ler(f, "<I", 4)
            f.seek(8, 1)  # offset do tensor
            # Camadas de embedding costumam ficar em F32/F16 mesmo em modelos
            # quantizados; o tipo dos blocos internos é o representativo.
            if "embd" not in nome and "norm" not in nome:
                return TIPOS_QUANT.get(tipo, f"tipo_{tipo}")
        return None
    except Exception:
        return None


def _normalizar(
    kv: dict[str, Any],
    versao: int,
    n_tensores: int,
    quantizacao: str | None,
    caminho: Path,
) -> dict[str, Any]:
    """Converte as chaves cruas do GGUF em um dicionário amigável."""
    arquitetura = kv.get("general.architecture", "desconhecida")

    def por_arq(sufixo: str) -> Any:
        return kv.get(f"{arquitetura}.{sufixo}")

    n_params = kv.get("general.parameter_count")
    return {
        "gguf_version": versao,
        "tensor_count": n_tensores,
        "architecture": arquitetura,
        "name": kv.get("general.name") or caminho.stem,
        "quantization": quantizacao or kv.get("general.file_type"),
        "context_length": por_arq("context_length"),
        "embedding_length": por_arq("embedding_length"),
        "block_count": por_arq("block_count"),
        "head_count": por_arq("attention.head_count"),
        "head_count_kv": por_arq("attention.head_count_kv"),
        "rope_freq_base": por_arq("rope.freq_base"),
        "vocab_size": kv.get("tokenizer.ggml.tokens") or por_arq("vocab_size"),
        "parameter_count": n_params,
        "parameters_human": _formatar_parametros(n_params),
        "license": kv.get("general.license"),
        "chat_template": bool(kv.get("tokenizer.chat_template")),
        "raw_keys": len(kv),
    }


def _formatar_parametros(n: Any) -> str | None:
    """Converte 7_000_000_000 em '7.0B'."""
    if not isinstance(n, (int, float)) or n <= 0:
        return None
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.0f}M"
    return str(int(n))
