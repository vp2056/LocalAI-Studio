"""Rotas de agentes personalizados."""

from __future__ import annotations

from fastapi import APIRouter

from ...schemas import (
    AgenteIn,
    AgenteOut,
    AgenteUpdateIn,
    MemoriaIn,
    MensagemSimples,
)
from ...services.agents import tools
from ...services.agents.service import servico_agentes
from ..deps import BancoDados, UsuarioAtual

router = APIRouter(prefix="/agents", tags=["Agentes"])


@router.get("", response_model=list[AgenteOut])
def listar(db: BancoDados, usuario: UsuarioAtual, apenas_ativos: bool = False):
    """Lista os agentes cadastrados."""
    return servico_agentes.listar(db, apenas_ativos)


@router.post("", response_model=AgenteOut, status_code=201)
def criar(dados: AgenteIn, db: BancoDados, usuario: UsuarioAtual):
    """Cria um agente personalizado."""
    agente = servico_agentes.criar(db, dados.model_dump())
    db.commit()
    return agente


@router.get("/tools", response_model=list[dict])
def listar_ferramentas(usuario: UsuarioAtual):
    """Catálogo de ferramentas que podem ser atribuídas a um agente."""
    return tools.listar()


@router.get("/{agente_id}", response_model=AgenteOut)
def obter(agente_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Detalhes de um agente."""
    return servico_agentes.obter(db, agente_id)


@router.patch("/{agente_id}", response_model=AgenteOut)
def atualizar(
    agente_id: int, dados: AgenteUpdateIn, db: BancoDados, usuario: UsuarioAtual
):
    """Edita um agente."""
    agente = servico_agentes.atualizar(
        db, agente_id, dados.model_dump(exclude_unset=True)
    )
    db.commit()
    return agente


@router.delete("/{agente_id}", response_model=MensagemSimples)
def remover(agente_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Exclui um agente."""
    servico_agentes.remover(db, agente_id)
    db.commit()
    return MensagemSimples(detail="Agente removido.")


@router.post("/{agente_id}/duplicate", response_model=AgenteOut, status_code=201)
def duplicar(agente_id: int, db: BancoDados, usuario: UsuarioAtual):
    """Cria uma cópia editável do agente."""
    copia = servico_agentes.duplicar(db, agente_id)
    db.commit()
    return copia


# ------------------------------------------------------------------- memória
@router.post("/{agente_id}/memory", response_model=AgenteOut)
def lembrar(agente_id: int, dados: MemoriaIn, db: BancoDados, usuario: UsuarioAtual):
    """Acrescenta um fato à memória permanente do agente."""
    agente = servico_agentes.lembrar(db, agente_id, dados.fato, origem=usuario.username)
    db.commit()
    return agente


@router.delete("/{agente_id}/memory", response_model=AgenteOut)
def esquecer(
    agente_id: int, db: BancoDados, usuario: UsuarioAtual, indice: int | None = None
):
    """Remove um fato específico ou limpa toda a memória do agente."""
    agente = servico_agentes.esquecer(db, agente_id, indice)
    db.commit()
    return agente
