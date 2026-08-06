"""
Ferramentas que os agentes podem utilizar.

Cada ferramenta é uma função registrada com nome, descrição e esquema de
parâmetros. Todas operam estritamente offline e dentro dos diretórios do
projeto — nenhuma ferramenta acessa a rede ou o sistema de arquivos externo.
"""

from __future__ import annotations

import ast
import logging
import operator
import platform
from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Registro global: nome -> metadados + função.
FERRAMENTAS: dict[str, dict[str, Any]] = {}


def ferramenta(nome: str, descricao: str, parametros: dict[str, Any] | None = None):
    """Decorador que registra uma função como ferramenta de agente."""

    def decorador(func: Callable[..., Any]) -> Callable[..., Any]:
        FERRAMENTAS[nome] = {
            "name": nome,
            "description": descricao,
            "parameters": parametros or {},
            "func": func,
        }
        return func

    return decorador


# ===========================================================================
# Calculadora
# ===========================================================================
# Operadores permitidos na avaliação de expressões. Usar a AST em vez de
# eval() impede execução de código arbitrário vindo do modelo.
_OPERADORES = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Teto do expoente: evita travar o processo com algo como 9**9**9.
_EXPOENTE_MAXIMO = 1000


@ferramenta(
    "calculadora",
    "Avalia uma expressão matemática (ex.: '(12*7)/3 + 2**5').",
    {"expressao": {"type": "string", "description": "Expressão a calcular"}},
)
def calculadora(expressao: str) -> str:
    """Avalia uma expressão aritmética com segurança."""

    def avaliar(no: ast.AST) -> float:
        if isinstance(no, ast.Constant):
            if isinstance(no.value, (int, float)):
                return no.value
            raise ValueError("Apenas números são aceitos.")
        if isinstance(no, ast.BinOp):
            op = _OPERADORES.get(type(no.op))
            if op is None:
                raise ValueError("Operador não permitido.")
            esquerda, direita = avaliar(no.left), avaliar(no.right)
            if isinstance(no.op, ast.Pow) and abs(direita) > _EXPOENTE_MAXIMO:
                raise ValueError("Expoente grande demais.")
            return op(esquerda, direita)
        if isinstance(no, ast.UnaryOp):
            op = _OPERADORES.get(type(no.op))
            if op is None:
                raise ValueError("Operador unário não permitido.")
            return op(avaliar(no.operand))
        raise ValueError("Expressão não suportada.")

    try:
        arvore = ast.parse(expressao, mode="eval")
        resultado = avaliar(arvore.body)
        return f"{expressao} = {resultado}"
    except ZeroDivisionError:
        return "Erro: divisão por zero."
    except Exception as exc:
        return f"Erro ao calcular: {exc}"


# ===========================================================================
# Data e hora
# ===========================================================================
@ferramenta("data_hora", "Informa a data e a hora atuais do sistema.")
def data_hora() -> str:
    """Data/hora local formatada em português."""
    agora = datetime.now().astimezone()
    dias = [
        "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo",
    ]
    return (
        f"{dias[agora.weekday()]}, {agora.strftime('%d/%m/%Y às %H:%M:%S')} "
        f"({agora.tzname()})"
    )


# ===========================================================================
# Busca na base de conhecimento
# ===========================================================================
@ferramenta(
    "busca_documentos",
    "Pesquisa trechos relevantes nos documentos indexados (RAG).",
    {
        "consulta": {"type": "string", "description": "O que procurar"},
        "k": {"type": "integer", "description": "Número de trechos (padrão 5)"},
    },
)
def busca_documentos(consulta: str, k: int = 5) -> str:
    """Consulta a base RAG e devolve os trechos formatados."""
    from ..rag.pipeline import pipeline

    resultados = pipeline.buscar(consulta, k=k)
    if not resultados:
        return "Nenhum trecho relevante encontrado na base de conhecimento."

    partes = []
    for i, r in enumerate(resultados, start=1):
        origem = r.document_title or "documento"
        if pagina := (r.meta or {}).get("page"):
            origem += f", p. {pagina}"
        partes.append(f"[{i}] ({origem}, score {r.score:.2f})\n{r.content}")
    return "\n\n".join(partes)


# ===========================================================================
# Informações do sistema
# ===========================================================================
@ferramenta("info_sistema", "Retorna informações do computador e dos recursos em uso.")
def info_sistema() -> str:
    """Resumo textual do estado da máquina."""
    from ..system.monitor import monitor

    dados = monitor.coletar()
    return (
        f"Sistema: {platform.system()} {platform.release()} ({platform.machine()})\n"
        f"CPU: {dados['cpu']['percent']}% em {dados['cpu']['cores']} núcleos\n"
        f"RAM: {dados['memory']['used_gb']:.1f} / {dados['memory']['total_gb']:.1f} GB "
        f"({dados['memory']['percent']}%)\n"
        f"Disco: {dados['disk']['free_gb']:.1f} GB livres de "
        f"{dados['disk']['total_gb']:.1f} GB"
    )


# ===========================================================================
# Listagem de modelos
# ===========================================================================
@ferramenta("listar_modelos", "Lista os modelos de IA instalados localmente.")
def listar_modelos() -> str:
    """Nomes e características dos modelos disponíveis."""
    from ..llm.manager import gerenciador

    modelos = gerenciador.listar()
    if not modelos:
        return "Nenhum modelo instalado."
    return "\n".join(
        f"- {m.name} ({m.format}, {m.parameters or '?'} parâmetros, "
        f"{m.quantization or 'sem quantização'}, contexto {m.context_length})"
        for m in modelos
    )


# ===========================================================================
# Execução
# ===========================================================================
def executar(nome: str, argumentos: dict[str, Any] | None = None) -> str:
    """
    Executa uma ferramenta pelo nome.

    Erros são devolvidos como texto: o agente deve poder reagir à falha em vez
    de interromper a conversa.
    """
    registro = FERRAMENTAS.get(nome)
    if registro is None:
        return f"Ferramenta '{nome}' não existe. Disponíveis: {', '.join(FERRAMENTAS)}"

    argumentos = dict(argumentos or {})
    # Modelos menores costumam omitir o nome do argumento; nesse caso o valor
    # posicional é atribuído ao primeiro parâmetro declarado da ferramenta.
    if "_posicional" in argumentos:
        valor = argumentos.pop("_posicional")
        primeiro = next(iter(registro["parameters"]), None)
        if primeiro:
            argumentos.setdefault(primeiro, valor)

    try:
        return str(registro["func"](**argumentos))
    except TypeError as exc:
        return f"Argumentos inválidos para '{nome}': {exc}"
    except Exception as exc:
        logger.exception("Erro na ferramenta '%s'", nome)
        return f"Erro ao executar '{nome}': {exc}"


def listar() -> list[dict[str, Any]]:
    """Catálogo das ferramentas, sem as referências de função."""
    return [
        {k: v for k, v in registro.items() if k != "func"}
        for registro in FERRAMENTAS.values()
    ]
