"""
Serviço de chat: monta o prompt, executa a geração e persiste o resultado.

Concentra a lógica compartilhada entre a rota HTTP ``POST /api/chat`` e o
WebSocket de streaming, para que ambos tenham exatamente o mesmo comportamento.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..core.exceptions import RecursoNaoEncontrado
from ..database.base import agora
from ..database.models import Agent, Conversation, Message
from .llm.base import Mensagem, ParametrosGeracao
from .llm.manager import gerenciador
from .plugins.manager import gerenciador_plugins
from .rag.pipeline import pipeline

logger = logging.getLogger(__name__)

# Quantas mensagens do histórico entram no prompt. O corte real é por tokens
# (ver _limitar_por_contexto); este é apenas um teto defensivo.
MAX_MENSAGENS_HISTORICO = 60

# Fração da janela de contexto reservada para a resposta do modelo.
RESERVA_RESPOSTA = 0.35


@dataclass(slots=True)
class ResultadoChat:
    """Resultado consolidado de uma geração."""

    content: str
    model: str
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    tokens: int = 0
    duration_ms: int = 0
    tokens_per_second: float = 0.0
    sources: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class ServicoChat:
    """Orquestração de uma rodada de conversa."""

    # ------------------------------------------------------------ conversa
    def obter_conversa(
        self, db: Session, conversa_id: int, user_id: int
    ) -> Conversation:
        """Carrega uma conversa garantindo que pertence ao usuário."""
        conversa = db.get(Conversation, conversa_id)
        if conversa is None or conversa.user_id != user_id:
            raise RecursoNaoEncontrado("Conversa não encontrada.")
        return conversa

    def criar_conversa(
        self,
        db: Session,
        user_id: int,
        *,
        titulo: str | None = None,
        modelo: str | None = None,
        agent_id: int | None = None,
        rag_collections: list[str] | None = None,
    ) -> Conversation:
        """Cria uma conversa nova."""
        conversa = Conversation(
            user_id=user_id,
            title=titulo or "Nova conversa",
            model_name=modelo or gerenciador.modelo_padrao(),
            agent_id=agent_id,
            rag_collections=rag_collections or [],
        )
        db.add(conversa)
        db.flush()
        return conversa

    # ------------------------------------------------------------- prompt
    def montar_prompt(
        self,
        db: Session,
        conversa: Conversation,
        entrada: str,
        *,
        usar_rag: bool = True,
    ) -> tuple[list[Mensagem], list[dict[str, Any]]]:
        """
        Monta a lista de mensagens enviada ao modelo.

        Ordem: instruções do sistema → memória do agente → contexto RAG →
        histórico → mensagem atual.
        """
        agente = db.get(Agent, conversa.agent_id) if conversa.agent_id else None
        mensagens: list[Mensagem] = []
        fontes: list[dict[str, Any]] = []

        # 1. Instruções do sistema.
        instrucoes = conversa.system_prompt or (agente.system_prompt if agente else "")
        if not instrucoes:
            instrucoes = (
                "Você é o assistente do LocalAI Studio. Responda de forma clara, "
                "correta e objetiva, em português do Brasil. Use Markdown e "
                "blocos de código com a linguagem indicada quando apropriado."
            )

        # 2. Memória permanente do agente.
        if agente and agente.memory_enabled and agente.memory:
            fatos = "\n".join(f"- {item.get('fact', '')}" for item in agente.memory[-40:])
            if fatos.strip():
                instrucoes += f"\n\nFatos memorizados sobre o usuário:\n{fatos}"

        mensagens.append(Mensagem(role="system", content=instrucoes))

        # 3. Contexto RAG.
        colecoes = list(conversa.rag_collections or [])
        if agente and agente.rag_collections:
            colecoes.extend(c for c in agente.rag_collections if c not in colecoes)

        if usar_rag and colecoes:
            contexto, resultados = pipeline.montar_contexto(entrada, colecoes=colecoes)
            if contexto:
                mensagens.append(Mensagem(role="system", content=contexto))
                fontes = [
                    {
                        "index": i,
                        "document_id": r.document_id,
                        "title": r.document_title,
                        "score": r.score,
                        "page": (r.meta or {}).get("page"),
                        "excerpt": r.content[:280],
                    }
                    for i, r in enumerate(resultados, start=1)
                ]

        # 4. Histórico.
        historico = db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversa.id,
                Message.role.in_(("user", "assistant")),
                Message.error.is_(None),
            )
            .order_by(Message.id.desc())
            .limit(MAX_MENSAGENS_HISTORICO)
        ).all()

        for msg in reversed(historico):
            if msg.content.strip():
                mensagens.append(Mensagem(role=msg.role, content=msg.content))

        # 5. Mensagem atual.
        mensagens.append(Mensagem(role="user", content=entrada))

        return self._limitar_por_contexto(mensagens, conversa.model_name), fontes

    def _limitar_por_contexto(
        self, mensagens: list[Mensagem], modelo: str | None
    ) -> list[Mensagem]:
        """
        Descarta as mensagens mais antigas até caber na janela de contexto.

        As mensagens de sistema e a última do usuário são sempre preservadas.
        """
        registro = gerenciador.obter(modelo) if modelo else None
        janela = registro.context_length if registro else settings.context_length
        orcamento = int(janela * (1 - RESERVA_RESPOSTA))

        def custo(m: Mensagem) -> int:
            # Estimativa de ~4 caracteres por token + margem do template de chat.
            return len(m.content) // 4 + 8

        fixas = [m for m in mensagens if m.role == "system"]
        conversacionais = [m for m in mensagens if m.role != "system"]

        total = sum(custo(m) for m in fixas)
        mantidas: list[Mensagem] = []

        # Percorre do mais recente para o mais antigo, preservando o fim.
        for mensagem in reversed(conversacionais):
            preco = custo(mensagem)
            if mantidas and total + preco > orcamento:
                break
            mantidas.append(mensagem)
            total += preco

        mantidas.reverse()
        if len(mantidas) < len(conversacionais):
            logger.debug(
                "Histórico truncado: %d de %d mensagens couberam no contexto.",
                len(mantidas),
                len(conversacionais),
            )
        return fixas + mantidas

    # ------------------------------------------------------------ geração
    def gerar_streaming(
        self,
        db: Session,
        conversa: Conversation,
        entrada: str,
        *,
        modelo: str | None = None,
        params: dict[str, Any] | None = None,
        usar_rag: bool = True,
        persistir_usuario: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """
        Executa uma rodada completa emitindo eventos de progresso.

        Eventos emitidos:
          ``{"type": "sources", ...}``  – trechos RAG utilizados;
          ``{"type": "token", ...}``    – fragmento de texto;
          ``{"type": "done", ...}``     – estatísticas finais;
          ``{"type": "error", ...}``    – falha durante a geração.
        """
        modelo = modelo or conversa.model_name or gerenciador.modelo_padrao()

        # Gancho de plugin: permite reescrever ou bloquear a entrada.
        entrada = gerenciador_plugins.executar_gancho(
            "on_message", entrada, conversa_id=conversa.id
        )

        mensagens, fontes = self.montar_prompt(db, conversa, entrada, usar_rag=usar_rag)

        if persistir_usuario:
            msg_usuario = Message(
                conversation_id=conversa.id, role="user", content=entrada
            )
            db.add(msg_usuario)
            db.flush()
        else:
            # Regeneração: reaproveita a última mensagem do usuário.
            msg_usuario = db.scalars(
                select(Message)
                .where(Message.conversation_id == conversa.id, Message.role == "user")
                .order_by(Message.id.desc())
                .limit(1)
            ).first()

        msg_assistente = Message(
            conversation_id=conversa.id,
            role="assistant",
            content="",
            model_name=modelo,
            meta={"sources": fontes} if fontes else {},
        )
        db.add(msg_assistente)
        db.flush()
        db.commit()

        if fontes:
            yield {"type": "sources", "sources": fontes}

        yield {
            "type": "start",
            "message_id": msg_assistente.id,
            "user_message_id": msg_usuario.id if msg_usuario else None,
            "model": modelo or "diagnóstico",
        }

        parametros = ParametrosGeracao.de_dict(
            {**(conversa.params or {}), **(params or {})}
        )

        partes: list[str] = []
        inicio = time.perf_counter()
        erro: str | None = None

        try:
            for pedaco in gerenciador.gerar(mensagens, modelo=modelo, params=parametros):
                partes.append(pedaco)
                yield {"type": "token", "content": pedaco}
        except Exception as exc:
            erro = str(exc)
            logger.exception("Falha na geração da conversa %d", conversa.id)
            yield {"type": "error", "error": erro}

        duracao = time.perf_counter() - inicio
        texto = "".join(partes)

        # Gancho de plugin sobre a resposta final.
        if texto:
            texto = gerenciador_plugins.executar_gancho(
                "on_response", texto, conversa_id=conversa.id
            )

        backend = gerenciador.carregar(modelo)
        tokens = backend.contar_tokens(texto) if texto else 0
        tps = round(tokens / duracao, 2) if duracao > 0 and tokens else 0.0

        msg_assistente.content = texto
        msg_assistente.tokens = tokens
        msg_assistente.duration_ms = int(duracao * 1000)
        msg_assistente.tokens_per_second = tps
        msg_assistente.error = erro

        conversa.message_count = (conversa.message_count or 0) + (
            2 if persistir_usuario else 1
        )
        conversa.total_tokens = (conversa.total_tokens or 0) + tokens
        conversa.last_message_at = agora()
        if modelo:
            conversa.model_name = modelo

        # Título automático a partir da primeira pergunta.
        if conversa.title == "Nova conversa" and entrada.strip():
            conversa.title = _titulo_automatico(entrada)

        if conversa.agent_id:
            agente = db.get(Agent, conversa.agent_id)
            if agente:
                agente.usage_count += 1

        db.commit()

        yield {
            "type": "done",
            "message_id": msg_assistente.id,
            "conversation_id": conversa.id,
            "title": conversa.title,
            "model": modelo or "diagnóstico",
            "tokens": tokens,
            "duration_ms": int(duracao * 1000),
            "tokens_per_second": tps,
            "sources": fontes,
            "error": erro,
        }

    def gerar(
        self,
        db: Session,
        conversa: Conversation,
        entrada: str,
        **kwargs: Any,
    ) -> ResultadoChat:
        """Versão não-streaming: consome o gerador e devolve o resultado."""
        final: dict[str, Any] = {}
        inicio_id: int | None = None
        partes: list[str] = []

        for evento in self.gerar_streaming(db, conversa, entrada, **kwargs):
            if evento["type"] == "token":
                partes.append(evento["content"])
            elif evento["type"] == "start":
                inicio_id = evento.get("user_message_id")
            elif evento["type"] == "done":
                final = evento

        return ResultadoChat(
            content="".join(partes),
            model=final.get("model", "desconhecido"),
            conversation_id=conversa.id,
            user_message_id=inicio_id or 0,
            assistant_message_id=final.get("message_id", 0),
            tokens=final.get("tokens", 0),
            duration_ms=final.get("duration_ms", 0),
            tokens_per_second=final.get("tokens_per_second", 0.0),
            sources=final.get("sources", []),
            error=final.get("error"),
        )


def _titulo_automatico(texto: str, limite: int = 60) -> str:
    """Deriva um título curto da primeira mensagem do usuário."""
    limpo = " ".join(texto.split())
    if len(limpo) <= limite:
        return limpo or "Nova conversa"
    # Corta na última palavra inteira antes do limite.
    corte = limpo[:limite].rsplit(" ", 1)[0]
    return f"{corte}…"


# Instância única.
servico_chat = ServicoChat()
