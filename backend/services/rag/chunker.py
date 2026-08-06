"""
Divisão de documentos em trechos (chunks) para indexação.

Estratégia recursiva: tenta quebrar nos limites semânticos mais fortes
(parágrafo → sentença → palavra) antes de cortar no meio de uma palavra.
Preserva marcadores de página inseridos pelo carregador de PDF, para que a
resposta do RAG possa citar a origem exata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...config import settings

# Separadores em ordem decrescente de força semântica.
SEPARADORES = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]

# Marcador emitido por loaders.carregar_pdf.
PADRAO_PAGINA = re.compile(r"\[\[página (\d+)\]\]")


@dataclass(slots=True)
class Trecho:
    """Um pedaço de documento pronto para virar embedding."""

    index: int
    content: str
    meta: dict[str, Any] = field(default_factory=dict)


def dividir(
    texto: str,
    *,
    tamanho: int | None = None,
    sobreposicao: int | None = None,
    metadados_base: dict[str, Any] | None = None,
) -> list[Trecho]:
    """
    Divide ``texto`` em trechos de ~``tamanho`` caracteres com ``sobreposicao``.

    A sobreposição preserva contexto na fronteira entre trechos, evitando que
    uma resposta seja cortada ao meio entre dois chunks.
    """
    tamanho = tamanho or settings.chunk_size
    sobreposicao = min(sobreposicao if sobreposicao is not None else settings.chunk_overlap, tamanho // 2)
    base = metadados_base or {}

    texto = texto.strip()
    if not texto:
        return []

    brutos = _dividir_recursivo(texto, tamanho)
    trechos: list[Trecho] = []
    pagina_atual: int | None = None

    for i, bruto in enumerate(brutos):
        # Acompanha em qual página do PDF o trecho começa.
        if achados := PADRAO_PAGINA.findall(bruto):
            pagina_atual = int(achados[0])

        conteudo = PADRAO_PAGINA.sub("", bruto).strip()
        if len(conteudo) < 24:  # trechos ínfimos não agregam à busca
            continue

        # Aplica a sobreposição puxando o final do trecho anterior.
        if sobreposicao and trechos:
            cauda = trechos[-1].content[-sobreposicao:]
            corte = cauda.find(" ")
            if corte > 0:
                conteudo = f"{cauda[corte + 1:]} {conteudo}"

        meta = dict(base)
        if pagina_atual is not None:
            meta["page"] = pagina_atual
        meta["char_start"] = i * tamanho

        trechos.append(Trecho(index=len(trechos), content=conteudo, meta=meta))

    return trechos


def _dividir_recursivo(texto: str, tamanho: int, nivel: int = 0) -> list[str]:
    """Quebra o texto tentando os separadores do mais forte ao mais fraco."""
    if len(texto) <= tamanho:
        return [texto]

    if nivel >= len(SEPARADORES):
        # Sem separador possível: corte duro de tamanho fixo.
        return [texto[i : i + tamanho] for i in range(0, len(texto), tamanho)]

    separador = SEPARADORES[nivel]
    partes = texto.split(separador)

    resultado: list[str] = []
    atual = ""

    for parte in partes:
        candidato = f"{atual}{separador}{parte}" if atual else parte

        if len(candidato) <= tamanho:
            atual = candidato
            continue

        if atual:
            resultado.append(atual)
        # A parte isolada ainda excede o limite: desce um nível de separador.
        if len(parte) > tamanho:
            resultado.extend(_dividir_recursivo(parte, tamanho, nivel + 1))
            atual = ""
        else:
            atual = parte

    if atual:
        resultado.append(atual)

    return [p.strip() for p in resultado if p.strip()]
