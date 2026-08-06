"""
WebSocket de chat com streaming e monitor de sistema em tempo real.

Protocolo do ``/ws/chat`` — o cliente envia::

    {"type": "chat", "mensagem": "...", "conversation_id": 1,
     "modelo": "...", "usar_rag": true, "params": {...}}
    {"type": "stop"}     — interrompe a geração em andamento
    {"type": "ping"}     — mantém a conexão viva

E recebe ``sources``, ``start``, ``token``, ``done``, ``error`` — os mesmos
eventos produzidos pelo serviço de chat.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ...database.session import SessionLocal
from ...services.chat import servico_chat
from ...services.system.monitor import monitor
from ..deps import usuario_websocket

logger = logging.getLogger(__name__)
router = APIRouter()

# Códigos de fechamento do protocolo WebSocket.
FECHAR_POLITICA = 1008
FECHAR_ERRO = 1011


class GerenciadorConexoes:
    """Conexões ativas e sinalização de cancelamento por conexão."""

    def __init__(self) -> None:
        self._ativas: set[WebSocket] = set()
        self._cancelar: dict[WebSocket, bool] = {}

    async def conectar(self, ws: WebSocket) -> None:
        await ws.accept()
        self._ativas.add(ws)
        self._cancelar[ws] = False

    def desconectar(self, ws: WebSocket) -> None:
        self._ativas.discard(ws)
        self._cancelar.pop(ws, None)

    def pedir_parada(self, ws: WebSocket) -> None:
        self._cancelar[ws] = True

    def deve_parar(self, ws: WebSocket) -> bool:
        return self._cancelar.get(ws, False)

    def limpar_parada(self, ws: WebSocket) -> None:
        self._cancelar[ws] = False

    @property
    def total(self) -> int:
        return len(self._ativas)


conexoes = GerenciadorConexoes()


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, token: str | None = Query(default=None)):
    """Canal de chat com streaming token a token."""
    db = SessionLocal()
    try:
        usuario = usuario_websocket(db, token)
    finally:
        db.close()

    if usuario is None:
        await websocket.close(code=FECHAR_POLITICA, reason="Não autenticado")
        return

    await conexoes.conectar(websocket)
    logger.info("WebSocket conectado: %s (%d ativas)", usuario.username, conexoes.total)

    try:
        while True:
            dados = await websocket.receive_json()
            tipo = dados.get("type", "chat")

            if tipo == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if tipo == "stop":
                conexoes.pedir_parada(websocket)
                continue

            if tipo != "chat":
                await websocket.send_json(
                    {"type": "error", "error": f"Tipo de mensagem desconhecido: {tipo}"}
                )
                continue

            await _processar_chat(websocket, usuario.id, dados)

    except WebSocketDisconnect:
        logger.info("WebSocket desconectado: %s", usuario.username)
    except Exception:
        logger.exception("Erro no WebSocket de %s", usuario.username)
        try:
            await websocket.close(code=FECHAR_ERRO)
        except RuntimeError:
            pass  # conexão já encerrada pelo cliente
    finally:
        conexoes.desconectar(websocket)


async def _processar_chat(
    websocket: WebSocket, user_id: int, dados: dict[str, Any]
) -> None:
    """Executa uma rodada de chat encaminhando os eventos ao cliente."""
    mensagem = (dados.get("mensagem") or "").strip()
    if not mensagem:
        await websocket.send_json({"type": "error", "error": "Mensagem vazia."})
        return

    conexoes.limpar_parada(websocket)
    db = SessionLocal()

    try:
        conversa_id = dados.get("conversation_id")
        if conversa_id:
            conversa = servico_chat.obter_conversa(db, int(conversa_id), user_id)
        else:
            conversa = servico_chat.criar_conversa(
                db,
                user_id,
                modelo=dados.get("modelo"),
                agent_id=dados.get("agent_id"),
            )
            db.commit()
            await websocket.send_json(
                {"type": "conversation", "conversation_id": conversa.id}
            )

        gerador = servico_chat.gerar_streaming(
            db,
            conversa,
            mensagem,
            modelo=dados.get("modelo"),
            params=dados.get("params"),
            usar_rag=dados.get("usar_rag", True),
        )

        # A geração é bloqueante (llama.cpp libera a GIL, mas o laço é síncrono).
        # Consumimos o iterador em um executor para não travar o event loop.
        laco = asyncio.get_running_loop()
        while True:
            evento = await laco.run_in_executor(None, _proximo, gerador)
            if evento is None:
                break

            await websocket.send_json(evento)

            if conexoes.deve_parar(websocket) and evento["type"] == "token":
                gerador.close()
                await websocket.send_json({"type": "stopped"})
                break

    except Exception as exc:
        logger.exception("Falha ao processar chat pelo WebSocket")
        await websocket.send_json({"type": "error", "error": str(exc)})
    finally:
        db.close()


def _proximo(gerador):
    """Avança o gerador uma posição; ``None`` quando esgotado."""
    try:
        return next(gerador)
    except StopIteration:
        return None


@router.websocket("/ws/system")
async def ws_sistema(websocket: WebSocket, token: str | None = Query(default=None)):
    """Envia métricas de recursos a cada segundo, para o painel."""
    db = SessionLocal()
    try:
        usuario = usuario_websocket(db, token)
    finally:
        db.close()

    if usuario is None:
        await websocket.close(code=FECHAR_POLITICA, reason="Não autenticado")
        return

    await websocket.accept()
    try:
        while True:
            await websocket.send_json({"type": "metrics", "data": monitor.resumo()})
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("Monitor via WebSocket encerrado.", exc_info=True)
