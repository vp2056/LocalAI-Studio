"""Rotas de chat, geração e histórico de conversas."""

from __future__ import annotations

import json
from dataclasses import asdict
import logging
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select

from ...core.exceptions import RecursoNaoEncontrado
from ...database.models import Conversation, Message
from ...schemas import (
    ChatIn,
    ChatOut,
    ConversaDetalheOut,
    ConversaIn,
    ConversaOut,
    ConversaUpdateIn,
    EditarMensagemIn,
    GenerateIn,
    GenerateOut,
    MensagemOut,
    MensagemSimples,
    PaginaOut,
)
from ...services.chat import servico_chat
from ...services.llm.base import Mensagem, ParametrosGeracao
from ...services.llm.manager import gerenciador
from ..deps import BancoDados, Pagina, UsuarioAtual

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Chat"])


# ===========================================================================
# Geração
# ===========================================================================
@router.post("/chat", response_model=ChatOut)
def chat(dados: ChatIn, usuario: UsuarioAtual, db: BancoDados):
    """
    Envia uma mensagem e recebe a resposta completa.

    Para respostas token a token use ``stream=true`` (SSE) ou o WebSocket
    ``/ws/chat``, que é o caminho preferido pela interface.
    """
    conversa = _resolver_conversa(db, dados, usuario.id)

    if dados.stream:
        return StreamingResponse(
            _sse(db, conversa, dados),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    resultado = servico_chat.gerar(
        db,
        conversa,
        dados.mensagem,
        modelo=dados.modelo,
        params=dados.params.model_dump(exclude_none=True) if dados.params else None,
        usar_rag=dados.usar_rag,
    )
    return ChatOut(**asdict(resultado))


def _sse(db, conversa, dados: ChatIn):
    """Adapta o gerador de eventos para o formato Server-Sent Events."""
    for evento in servico_chat.gerar_streaming(
        db,
        conversa,
        dados.mensagem,
        modelo=dados.modelo,
        params=dados.params.model_dump(exclude_none=True) if dados.params else None,
        usar_rag=dados.usar_rag,
    ):
        yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/generate", response_model=GenerateOut)
def generate(dados: GenerateIn, usuario: UsuarioAtual):
    """
    Geração direta a partir de um prompt, sem conversa nem persistência.

    Útil para integrações e tarefas pontuais (resumir, traduzir, classificar).
    """
    mensagens = []
    if dados.system:
        mensagens.append(Mensagem(role="system", content=dados.system))
    mensagens.append(Mensagem(role="user", content=dados.prompt))

    resultado = gerenciador.gerar_completo(
        mensagens,
        modelo=dados.modelo,
        params=ParametrosGeracao.de_dict(
            dados.params.model_dump(exclude_none=True) if dados.params else None
        ),
    )
    return GenerateOut(**resultado)


# ===========================================================================
# Conversas
# ===========================================================================
@router.get("/conversations", response_model=PaginaOut)
def listar_conversas(
    usuario: UsuarioAtual,
    db: BancoDados,
    pagina: Pagina,
    busca: Annotated[str | None, Query(max_length=200)] = None,
    arquivadas: bool = False,
    fixadas: bool | None = None,
):
    """Lista as conversas do usuário, com busca por título e conteúdo."""
    condicoes = [
        Conversation.user_id == usuario.id,
        Conversation.archived.is_(arquivadas),
    ]
    if fixadas is not None:
        condicoes.append(Conversation.pinned.is_(fixadas))

    if busca:
        padrao = f"%{busca}%"
        # Busca também no texto das mensagens, não só no título.
        subconsulta = select(Message.conversation_id).where(
            Message.content.ilike(padrao)
        )
        condicoes.append(
            or_(Conversation.title.ilike(padrao), Conversation.id.in_(subconsulta))
        )

    total = db.scalar(select(func.count(Conversation.id)).where(*condicoes)) or 0

    conversas = db.scalars(
        select(Conversation)
        .where(*condicoes)
        # Fixadas primeiro, depois as mais recentes.
        .order_by(
            Conversation.pinned.desc(),
            func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
        )
        .offset(pagina.offset)
        .limit(pagina.per_page)
    ).all()

    return pagina.envelope(
        [ConversaOut.model_validate(c) for c in conversas], total
    )


@router.post("/conversations", response_model=ConversaOut, status_code=201)
def criar_conversa(dados: ConversaIn, usuario: UsuarioAtual, db: BancoDados):
    """Cria uma conversa vazia."""
    conversa = servico_chat.criar_conversa(
        db,
        usuario.id,
        titulo=dados.title,
        modelo=dados.model_name,
        agent_id=dados.agent_id,
        rag_collections=dados.rag_collections,
    )
    if dados.system_prompt:
        conversa.system_prompt = dados.system_prompt
    if dados.params:
        conversa.params = dados.params
    db.commit()
    return conversa


@router.get("/conversations/{conversa_id}", response_model=ConversaDetalheOut)
def obter_conversa(conversa_id: int, usuario: UsuarioAtual, db: BancoDados):
    """Conversa com todas as suas mensagens."""
    conversa = servico_chat.obter_conversa(db, conversa_id, usuario.id)
    detalhe = ConversaDetalheOut.model_validate(conversa)
    detalhe.messages = [MensagemOut.model_validate(m) for m in conversa.messages]
    return detalhe


@router.patch("/conversations/{conversa_id}", response_model=ConversaOut)
def atualizar_conversa(
    conversa_id: int, dados: ConversaUpdateIn, usuario: UsuarioAtual, db: BancoDados
):
    """Renomeia, fixa, arquiva ou reconfigura uma conversa."""
    conversa = servico_chat.obter_conversa(db, conversa_id, usuario.id)
    for campo, valor in dados.model_dump(exclude_none=True).items():
        setattr(conversa, campo, valor)
    db.commit()
    return conversa


@router.delete("/conversations/{conversa_id}", response_model=MensagemSimples)
def remover_conversa(conversa_id: int, usuario: UsuarioAtual, db: BancoDados):
    """Exclui a conversa e todas as suas mensagens."""
    conversa = servico_chat.obter_conversa(db, conversa_id, usuario.id)
    db.delete(conversa)
    db.commit()
    return MensagemSimples(detail="Conversa excluída.")


@router.get("/conversations/{conversa_id}/export")
def exportar_conversa(
    conversa_id: int,
    usuario: UsuarioAtual,
    db: BancoDados,
    formato: Annotated[str, Query(pattern="^(markdown|json|txt)$")] = "markdown",
):
    """Exporta a conversa em Markdown, JSON ou texto puro."""
    conversa = servico_chat.obter_conversa(db, conversa_id, usuario.id)

    if formato == "json":
        conteudo = json.dumps(
            {
                "title": conversa.title,
                "model": conversa.model_name,
                "created_at": conversa.created_at.isoformat(),
                "messages": [
                    {
                        "role": m.role,
                        "content": m.content,
                        "model": m.model_name,
                        "tokens": m.tokens,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in conversa.messages
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        tipo, extensao = "application/json", "json"
    elif formato == "txt":
        conteudo = "\n\n".join(
            f"{'VOCÊ' if m.role == 'user' else 'ASSISTENTE'}: {m.content}"
            for m in conversa.messages
            if m.role in ("user", "assistant")
        )
        tipo, extensao = "text/plain", "txt"
    else:
        linhas = [
            f"# {conversa.title}",
            "",
            f"*Modelo: {conversa.model_name or 'não informado'} · "
            f"Criada em {conversa.created_at.strftime('%d/%m/%Y %H:%M')}*",
            "",
            "---",
            "",
        ]
        for m in conversa.messages:
            if m.role not in ("user", "assistant"):
                continue
            linhas.append(f"### {'Você' if m.role == 'user' else 'Assistente'}")
            linhas.append("")
            linhas.append(m.content)
            linhas.append("")
        conteudo = "\n".join(linhas)
        tipo, extensao = "text/markdown", "md"

    nome = "".join(c if c.isalnum() or c in " -_" else "_" for c in conversa.title)[:60]
    return StreamingResponse(
        iter([conteudo.encode("utf-8")]),
        media_type=f"{tipo}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nome.strip() or "conversa"}.{extensao}"'
        },
    )


# ===========================================================================
# Mensagens
# ===========================================================================
@router.get("/conversations/{conversa_id}/messages", response_model=list[MensagemOut])
def listar_mensagens(
    conversa_id: int,
    usuario: UsuarioAtual,
    db: BancoDados,
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
    antes_de: int | None = None,
):
    """Mensagens da conversa, com paginação por cursor (para rolagem infinita)."""
    servico_chat.obter_conversa(db, conversa_id, usuario.id)

    condicoes = [Message.conversation_id == conversa_id]
    if antes_de:
        condicoes.append(Message.id < antes_de)

    mensagens = db.scalars(
        select(Message).where(*condicoes).order_by(Message.id.desc()).limit(limite)
    ).all()
    return [MensagemOut.model_validate(m) for m in reversed(mensagens)]


@router.patch("/messages/{mensagem_id}", response_model=ChatOut | MensagemOut)
def editar_mensagem(
    mensagem_id: int, dados: EditarMensagemIn, usuario: UsuarioAtual, db: BancoDados
):
    """
    Edita uma mensagem do usuário.

    Com ``regenerar=true``, as mensagens seguintes são descartadas e uma nova
    resposta é gerada a partir do texto corrigido.
    """
    mensagem = db.get(Message, mensagem_id)
    if mensagem is None:
        raise RecursoNaoEncontrado("Mensagem não encontrada.")

    conversa = servico_chat.obter_conversa(db, mensagem.conversation_id, usuario.id)

    if mensagem.role != "user":
        raise RecursoNaoEncontrado("Apenas mensagens do usuário podem ser editadas.")

    mensagem.content = dados.content
    mensagem.edited = True

    if not dados.regenerar:
        db.commit()
        return MensagemOut.model_validate(mensagem)

    # Remove tudo o que veio depois: o histórico posterior ficou inválido.
    db.execute(
        delete(Message).where(
            Message.conversation_id == conversa.id, Message.id > mensagem_id
        )
    )
    db.commit()

    resultado = servico_chat.gerar(
        db, conversa, dados.content, persistir_usuario=False
    )
    return ChatOut(**asdict(resultado))


@router.post("/messages/{mensagem_id}/regenerate", response_model=ChatOut)
def regenerar(mensagem_id: int, usuario: UsuarioAtual, db: BancoDados):
    """Descarta uma resposta do assistente e gera outra."""
    mensagem = db.get(Message, mensagem_id)
    if mensagem is None or mensagem.role != "assistant":
        raise RecursoNaoEncontrado("Resposta não encontrada.")

    conversa = servico_chat.obter_conversa(db, mensagem.conversation_id, usuario.id)

    pergunta = db.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversa.id,
            Message.role == "user",
            Message.id < mensagem_id,
        )
        .order_by(Message.id.desc())
        .limit(1)
    ).first()

    if pergunta is None:
        raise RecursoNaoEncontrado("Não há pergunta correspondente para regenerar.")

    db.execute(
        delete(Message).where(
            Message.conversation_id == conversa.id, Message.id >= mensagem_id
        )
    )
    db.commit()

    resultado = servico_chat.gerar(
        db, conversa, pergunta.content, persistir_usuario=False
    )
    return ChatOut(**asdict(resultado))


@router.delete("/messages/{mensagem_id}", response_model=MensagemSimples)
def remover_mensagem(mensagem_id: int, usuario: UsuarioAtual, db: BancoDados):
    """Exclui uma mensagem isolada."""
    mensagem = db.get(Message, mensagem_id)
    if mensagem is None:
        raise RecursoNaoEncontrado("Mensagem não encontrada.")
    servico_chat.obter_conversa(db, mensagem.conversation_id, usuario.id)
    db.delete(mensagem)
    db.commit()
    return MensagemSimples(detail="Mensagem excluída.")


# ===========================================================================
# Histórico global
# ===========================================================================
@router.get("/history", response_model=PaginaOut)
def historico(
    usuario: UsuarioAtual,
    db: BancoDados,
    pagina: Pagina,
    busca: Annotated[str | None, Query(max_length=200)] = None,
):
    """Busca em todas as mensagens do usuário (pesquisa global)."""
    condicoes = [Conversation.user_id == usuario.id]
    if busca:
        condicoes.append(Message.content.ilike(f"%{busca}%"))

    base = select(Message).join(Conversation).where(*condicoes)

    total = (
        db.scalar(
            select(func.count(Message.id)).join(Conversation).where(*condicoes)
        )
        or 0
    )
    mensagens = db.scalars(
        base.order_by(Message.id.desc()).offset(pagina.offset).limit(pagina.per_page)
    ).all()

    return pagina.envelope(
        [MensagemOut.model_validate(m) for m in mensagens], total
    )


def _resolver_conversa(db, dados: ChatIn, user_id: int) -> Conversation:
    """Obtém a conversa indicada ou cria uma nova."""
    if dados.conversation_id:
        return servico_chat.obter_conversa(db, dados.conversation_id, user_id)
    return servico_chat.criar_conversa(
        db, user_id, modelo=dados.modelo, agent_id=dados.agent_id
    )
