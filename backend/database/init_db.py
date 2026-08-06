"""
Inicialização (seed) do banco: cria tabelas, usuário administrador padrão,
agentes de exemplo e configurações iniciais.

É idempotente: pode ser executado a cada inicialização sem duplicar dados.
"""

from __future__ import annotations

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..core.security import hash_senha
from .models import Agent, Setting, User
from .session import criar_tabelas, sessao

logger = logging.getLogger(__name__)

# Credenciais padrão do primeiro acesso. A senha é aleatória e exibida uma
# única vez no console/log — evita instâncias abertas com "admin/admin".
USUARIO_PADRAO = "admin"

AGENTES_PADRAO = [
    {
        "name": "Assistente Geral",
        "avatar": "🤖",
        "description": "Assistente equilibrado para tarefas do dia a dia.",
        "system_prompt": (
            "Você é um assistente prestativo, direto e honesto. "
            "Responda em português do Brasil, salvo pedido em contrário. "
            "Quando não souber algo, diga que não sabe."
        ),
        "temperature": 0.7,
        "tools": ["calculadora", "data_hora"],
    },
    {
        "name": "Programador",
        "avatar": "💻",
        "description": "Especialista em programação e revisão de código.",
        "system_prompt": (
            "Você é um engenheiro de software sênior. Forneça código correto, "
            "idiomático e comentado. Sempre indique a linguagem nos blocos de "
            "código e aponte riscos ou casos de borda relevantes."
        ),
        "temperature": 0.3,
        "tools": ["calculadora"],
    },
    {
        "name": "Analista de Documentos",
        "avatar": "📚",
        "description": "Responde com base nos documentos indexados (RAG).",
        "system_prompt": (
            "Responda exclusivamente com base no CONTEXTO fornecido. "
            "Cite o trecho de origem ao afirmar algo. Se o contexto não "
            "contiver a resposta, diga claramente que não foi encontrada."
        ),
        "temperature": 0.2,
        "tools": ["busca_documentos"],
        "rag_collections": ["default"],
    },
]

CONFIGURACOES_PADRAO = [
    ("ui.theme", "dark", "interface", "Tema da interface: dark | light | auto"),
    ("ui.language", "pt-BR", "interface", "Idioma da interface"),
    ("ui.font_size", 15, "interface", "Tamanho da fonte do chat (px)"),
    ("chat.stream", True, "chat", "Habilitar respostas em streaming"),
    ("chat.show_stats", True, "chat", "Exibir tokens/s e tempo de geração"),
    ("chat.auto_title", True, "chat", "Gerar título automático da conversa"),
    ("rag.enabled", True, "rag", "Habilitar consulta automática à base RAG"),
    ("rag.top_k", settings.rag_top_k, "rag", "Trechos recuperados por consulta"),
    ("backup.enabled", settings.backup_enabled, "backup", "Backup automático"),
    (
        "backup.interval_hours",
        settings.backup_interval_hours,
        "backup",
        "Intervalo entre backups automáticos (horas)",
    ),
]


def _criar_admin(db: Session) -> str | None:
    """Cria o usuário administrador se ainda não houver nenhum usuário."""
    if db.scalar(select(User).limit(1)) is not None:
        return None

    senha = secrets.token_urlsafe(12)
    admin = User(
        username=USUARIO_PADRAO,
        password_hash=hash_senha(senha),
        full_name="Administrador",
        role="admin",
        preferences={"theme": "dark", "language": "pt-BR"},
    )
    db.add(admin)
    db.flush()
    return senha


def _criar_agentes(db: Session) -> int:
    """Cria os agentes de exemplo ausentes."""
    criados = 0
    for dados in AGENTES_PADRAO:
        existente = db.scalar(select(Agent).where(Agent.name == dados["name"]))
        if existente is None:
            db.add(Agent(**dados))
            criados += 1
    return criados


def _criar_configuracoes(db: Session) -> int:
    """Insere as configurações padrão ainda não presentes."""
    criadas = 0
    for chave, valor, categoria, descricao in CONFIGURACOES_PADRAO:
        existente = db.scalar(select(Setting).where(Setting.key == chave))
        if existente is None:
            db.add(
                Setting(
                    key=chave, value=valor, category=categoria, description=descricao
                )
            )
            criadas += 1
    return criadas


def inicializar_banco() -> str | None:
    """
    Prepara o banco para uso.

    Retorna a senha do administrador quando ela é gerada nesta execução
    (primeira instalação); ``None`` nas execuções seguintes.
    """
    criar_tabelas()

    with sessao() as db:
        senha_admin = _criar_admin(db)
        agentes = _criar_agentes(db)
        configs = _criar_configuracoes(db)

    if agentes:
        logger.info("Agentes padrão criados: %d", agentes)
    if configs:
        logger.info("Configurações padrão criadas: %d", configs)

    if senha_admin:
        logger.warning(
            "\n%s\n  PRIMEIRO ACESSO — anote estas credenciais:\n"
            "    usuário: %s\n    senha:   %s\n"
            "  Altere a senha em Configurações após entrar.\n%s",
            "=" * 62,
            USUARIO_PADRAO,
            senha_admin,
            "=" * 62,
        )
    return senha_admin


if __name__ == "__main__":  # execução direta: python -m backend.database.init_db
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    inicializar_banco()
