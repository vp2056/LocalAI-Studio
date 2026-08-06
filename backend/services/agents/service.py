"""
Serviço de agentes: CRUD, memória permanente e execução de ferramentas.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.exceptions import RecursoNaoEncontrado
from ...database.base import agora
from ...database.models import Agent
from . import tools

logger = logging.getLogger(__name__)

# Quantos fatos a memória de um agente retém antes de descartar os mais antigos.
LIMITE_MEMORIA = 200

# Sintaxe que o modelo pode emitir para acionar uma ferramenta.
PADRAO_CHAMADA = re.compile(r"\[\[ferramenta:(\w+)(?:\((.*?)\))?\]\]", re.S)


class ServicoAgentes:
    """Regras de negócio dos agentes personalizados."""

    # ----------------------------------------------------------------- CRUD
    def listar(self, db: Session, apenas_ativos: bool = False) -> list[Agent]:
        consulta = select(Agent)
        if apenas_ativos:
            consulta = consulta.where(Agent.is_active.is_(True))
        return list(db.scalars(consulta.order_by(Agent.name)).all())

    def obter(self, db: Session, agent_id: int) -> Agent:
        agente = db.get(Agent, agent_id)
        if agente is None:
            raise RecursoNaoEncontrado("Agente não encontrado.")
        return agente

    def criar(self, db: Session, dados: dict[str, Any]) -> Agent:
        """Cria um agente, validando as ferramentas informadas."""
        dados = dict(dados)
        dados["tools"] = self._validar_ferramentas(dados.get("tools"))
        agente = Agent(**dados)
        db.add(agente)
        db.flush()
        logger.info("Agente criado: %s (id=%d)", agente.name, agente.id)
        return agente

    def atualizar(self, db: Session, agent_id: int, dados: dict[str, Any]) -> Agent:
        agente = self.obter(db, agent_id)
        if "tools" in dados:
            dados["tools"] = self._validar_ferramentas(dados["tools"])
        for campo, valor in dados.items():
            if valor is not None and hasattr(agente, campo):
                setattr(agente, campo, valor)
        db.flush()
        return agente

    def remover(self, db: Session, agent_id: int) -> None:
        agente = self.obter(db, agent_id)
        db.delete(agente)
        logger.info("Agente removido: %s", agente.name)

    def duplicar(self, db: Session, agent_id: int) -> Agent:
        """Cria uma cópia editável de um agente existente."""
        original = self.obter(db, agent_id)
        copia = Agent(
            name=f"{original.name} (cópia)",
            avatar=original.avatar,
            description=original.description,
            system_prompt=original.system_prompt,
            model_name=original.model_name,
            temperature=original.temperature,
            top_p=original.top_p,
            top_k=original.top_k,
            max_tokens=original.max_tokens,
            tools=list(original.tools or []),
            rag_collections=list(original.rag_collections or []),
            memory_enabled=original.memory_enabled,
        )
        db.add(copia)
        db.flush()
        return copia

    def _validar_ferramentas(self, nomes: list[str] | None) -> list[str]:
        """Descarta ferramentas inexistentes em vez de falhar a criação."""
        if not nomes:
            return []
        validas, invalidas = [], []
        for nome in nomes:
            (validas if nome in tools.FERRAMENTAS else invalidas).append(nome)
        if invalidas:
            logger.warning("Ferramentas ignoradas (inexistentes): %s", invalidas)
        return validas

    # --------------------------------------------------------------- memória
    def lembrar(self, db: Session, agent_id: int, fato: str, origem: str = "usuário") -> Agent:
        """Adiciona um fato à memória permanente do agente."""
        agente = self.obter(db, agent_id)
        memoria = list(agente.memory or [])
        memoria.append(
            {"fact": fato.strip(), "source": origem, "at": agora().isoformat()}
        )
        # Reatribuição necessária: SQLAlchemy não detecta mutação em JSON.
        agente.memory = memoria[-LIMITE_MEMORIA:]
        db.flush()
        return agente

    def esquecer(self, db: Session, agent_id: int, indice: int | None = None) -> Agent:
        """Remove um fato específico ou limpa toda a memória."""
        agente = self.obter(db, agent_id)
        if indice is None:
            agente.memory = []
        else:
            memoria = list(agente.memory or [])
            if 0 <= indice < len(memoria):
                memoria.pop(indice)
            agente.memory = memoria
        db.flush()
        return agente

    # ------------------------------------------------------------ ferramentas
    def processar_ferramentas(self, agente: Agent, texto: str) -> tuple[str, list[dict]]:
        """
        Executa as chamadas de ferramenta presentes na resposta do modelo.

        Reconhece a sintaxe ``[[ferramenta:nome(arg=valor)]]`` e substitui cada
        ocorrência pelo resultado. Ferramentas não habilitadas para o agente são
        recusadas explicitamente.
        """
        permitidas = set(agente.tools or [])
        if not permitidas:
            return texto, []

        execucoes: list[dict[str, Any]] = []

        def substituir(correspondencia: re.Match[str]) -> str:
            nome = correspondencia.group(1)
            bruto = correspondencia.group(2) or ""

            if nome not in permitidas:
                return f"[ferramenta '{nome}' não habilitada para este agente]"

            argumentos = _parsear_argumentos(bruto)
            resultado = tools.executar(nome, argumentos)
            execucoes.append({"tool": nome, "args": argumentos, "result": resultado})
            return f"\n\n> **{nome}** → {resultado}\n\n"

        return PADRAO_CHAMADA.sub(substituir, texto), execucoes

    def instrucoes_ferramentas(self, agente: Agent) -> str:
        """Bloco de instruções que ensina o modelo a acionar as ferramentas."""
        habilitadas = [
            tools.FERRAMENTAS[n] for n in (agente.tools or []) if n in tools.FERRAMENTAS
        ]
        if not habilitadas:
            return ""

        linhas = [
            "Você pode usar as ferramentas abaixo escrevendo, em uma linha isolada:",
            "[[ferramenta:nome(argumento=valor)]]",
            "",
            "Ferramentas disponíveis:",
        ]
        for f in habilitadas:
            params = ", ".join(f["parameters"]) if f["parameters"] else "sem argumentos"
            linhas.append(f"- {f['name']}: {f['description']} ({params})")
        return "\n".join(linhas)


def _parsear_argumentos(bruto: str) -> dict[str, Any]:
    """
    Converte ``a=1, b="texto"`` em dicionário.

    Aceita também um único valor posicional, atribuído ao primeiro parâmetro
    usual (``expressao`` ou ``consulta``), pois modelos pequenos costumam
    omitir o nome do argumento.
    """
    bruto = bruto.strip()
    if not bruto:
        return {}

    if "=" not in bruto:
        return {"_posicional": bruto.strip("\"'")}

    argumentos: dict[str, Any] = {}
    for parte in _dividir_argumentos(bruto):
        if "=" not in parte:
            continue
        chave, _, valor = parte.partition("=")
        valor = valor.strip().strip("\"'")
        # Converte números quando possível; o resto permanece string.
        if valor.lstrip("-").isdigit():
            argumentos[chave.strip()] = int(valor)
        else:
            try:
                argumentos[chave.strip()] = float(valor)
            except ValueError:
                argumentos[chave.strip()] = valor
    return argumentos


def _dividir_argumentos(bruto: str) -> list[str]:
    """Divide por vírgulas que não estejam dentro de aspas."""
    partes, atual, aspas = [], [], ""
    for caractere in bruto:
        if caractere in "\"'":
            aspas = "" if aspas == caractere else (aspas or caractere)
            atual.append(caractere)
        elif caractere == "," and not aspas:
            partes.append("".join(atual))
            atual = []
        else:
            atual.append(caractere)
    if atual:
        partes.append("".join(atual))
    return partes


# Instância única.
servico_agentes = ServicoAgentes()
