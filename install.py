#!/usr/bin/env python3
"""
Instalador do LocalAI Studio.

Cria o ambiente virtual, instala as dependências (obrigatórias e as opcionais
escolhidas), prepara os diretórios e inicializa o banco.

Uso:
    python install.py                  # instalação guiada
    python install.py --minimo         # apenas o núcleo
    python install.py --completo       # núcleo + todos os extras
    python install.py --sem-venv       # instala no Python atual
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
VENV = RAIZ / ".venv"

# Pacotes opcionais agrupados por recurso.
GRUPOS: dict[str, dict] = {
    "gguf": {
        "titulo": "Modelos GGUF (llama.cpp) — o motor de inferência mais comum",
        "pacotes": ["llama-cpp-python"],
        "recomendado": True,
    },
    "rag": {
        "titulo": "RAG com busca semântica (embeddings + índice FAISS)",
        "pacotes": ["sentence-transformers", "faiss-cpu"],
        "recomendado": True,
    },
    "documentos": {
        "titulo": "Leitura de PDF, DOCX e HTML",
        "pacotes": ["pypdf", "python-docx", "beautifulsoup4"],
        "recomendado": True,
    },
    "transformers": {
        "titulo": "Modelos HuggingFace (safetensors) — requer PyTorch (~2 GB)",
        "pacotes": ["transformers", "torch", "safetensors"],
        "recomendado": False,
    },
    "onnx": {
        "titulo": "Modelos ONNX",
        "pacotes": ["onnxruntime"],
        "recomendado": False,
    },
    "ocr": {
        "titulo": "OCR — texto de imagens e PDFs digitalizados",
        "pacotes": ["pytesseract", "Pillow", "pdf2image"],
        "recomendado": False,
        "aviso": "Requer também o binário 'tesseract' instalado no sistema.",
    },
    "voz": {
        "titulo": "Voz — transcrição de áudio e leitura em voz alta",
        "pacotes": ["faster-whisper", "pyttsx3"],
        "recomendado": False,
    },
    "imagens": {
        "titulo": "Geração de imagens com modelos de difusão — requer PyTorch",
        "pacotes": ["diffusers", "torch", "accelerate"],
        "recomendado": False,
    },
    "desktop": {
        "titulo": "Aplicativo desktop (janela nativa)",
        "pacotes": ["PySide6"],
        "recomendado": False,
    },
}

DIRETORIOS = [
    "database", "models", "documents", "plugins", "logs", "config",
    "uploads", "downloads", "temp", "backups",
]

VERSAO_MINIMA = (3, 10)


# ---------------------------------------------------------------------------
# Apresentação
# ---------------------------------------------------------------------------
def titulo(texto: str) -> None:
    print(f"\n{'─' * 66}\n  {texto}\n{'─' * 66}")


def passo(texto: str) -> None:
    print(f"  → {texto}")


def ok(texto: str) -> None:
    print(f"  ✓ {texto}")


def falha(texto: str) -> None:
    print(f"  ✗ {texto}")


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------
def verificar_python() -> None:
    """Aborta se a versão do Python for incompatível."""
    if sys.version_info < VERSAO_MINIMA:
        falha(
            f"Python {'.'.join(map(str, VERSAO_MINIMA))}+ é necessário "
            f"(encontrado {platform.python_version()})."
        )
        sys.exit(1)
    ok(f"Python {platform.python_version()} em {platform.system()}")


def criar_diretorios() -> None:
    """Cria a árvore de diretórios de trabalho."""
    for nome in DIRETORIOS:
        (RAIZ / nome).mkdir(parents=True, exist_ok=True)
    ok(f"{len(DIRETORIOS)} diretórios prontos")


def criar_venv() -> Path:
    """Cria o ambiente virtual e devolve o caminho do interpretador."""
    if not VENV.exists():
        passo("Criando ambiente virtual em .venv…")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        ok("Ambiente virtual criado")
    else:
        ok("Ambiente virtual já existe")

    return executavel_venv()


def executavel_venv() -> Path:
    """Caminho do Python dentro do ambiente virtual."""
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def instalar(python: Path, pacotes: list[str], descricao: str) -> bool:
    """Instala pacotes com pip; devolve False em caso de falha."""
    passo(f"Instalando {descricao}…")
    resultado = subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", *pacotes],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        falha(f"Falha ao instalar {descricao}")
        # Apenas as últimas linhas: o log completo do pip é longo demais.
        print("\n".join(resultado.stderr.strip().splitlines()[-8:]))
        return False
    ok(descricao)
    return True


def escolher_grupos(modo: str) -> list[str]:
    """Define quais grupos opcionais instalar."""
    if modo == "minimo":
        return []
    if modo == "completo":
        return list(GRUPOS)

    titulo("Recursos opcionais")
    print("  Responda s/n para cada item (Enter aceita a sugestão).\n")

    escolhidos = []
    for chave, grupo in GRUPOS.items():
        padrao = "S/n" if grupo["recomendado"] else "s/N"
        print(f"  {grupo['titulo']}")
        if aviso := grupo.get("aviso"):
            print(f"    ({aviso})")

        resposta = input(f"    Instalar? [{padrao}] ").strip().lower()
        if not resposta:
            quer = grupo["recomendado"]
        else:
            quer = resposta.startswith("s")

        if quer:
            escolhidos.append(chave)
        print()

    return escolhidos


def inicializar_banco(python: Path) -> None:
    """Cria as tabelas e o usuário administrador."""
    passo("Inicializando o banco de dados…")
    resultado = subprocess.run(
        [str(python), "-m", "backend.database.init_db"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    # A saída contém as credenciais do primeiro acesso; exibimos por inteiro.
    saida = (resultado.stdout + resultado.stderr).strip()
    if saida:
        print("\n" + saida + "\n")
    if resultado.returncode == 0:
        ok("Banco de dados pronto")
    else:
        falha("Falha ao inicializar o banco")


def verificar_tesseract() -> None:
    """Avisa se o OCR foi pedido sem o binário do Tesseract presente."""
    if shutil.which("tesseract") is None:
        print(
            "\n  Atenção: o binário 'tesseract' não foi encontrado no PATH.\n"
            "    Linux:   sudo apt install tesseract-ocr tesseract-ocr-por\n"
            "    macOS:   brew install tesseract tesseract-lang\n"
            "    Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
        )


# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Instalador do LocalAI Studio.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--minimo", action="store_true", help="Somente o núcleo")
    grupo.add_argument("--completo", action="store_true", help="Núcleo + todos os extras")
    parser.add_argument(
        "--sem-venv", action="store_true", help="Instalar no Python atual"
    )
    args = parser.parse_args()

    print(
        "\n"
        "  ╭────────────────────────────────────────────────────────────╮\n"
        "  │  LocalAI Studio — Instalação                               │\n"
        "  │  Plataforma de inteligência artificial local e offline     │\n"
        "  ╰────────────────────────────────────────────────────────────╯"
    )

    titulo("Verificações")
    verificar_python()
    criar_diretorios()

    titulo("Ambiente")
    python = Path(sys.executable) if args.sem_venv else criar_venv()
    if args.sem_venv:
        ok(f"Usando o Python atual: {python}")

    titulo("Dependências obrigatórias")
    instalar(python, ["pip", "setuptools", "wheel"], "ferramentas de empacotamento")
    if not instalar(python, ["-r", str(RAIZ / "requirements.txt")], "núcleo"):
        falha("A instalação do núcleo falhou. Corrija os erros acima e repita.")
        return 1

    modo = "minimo" if args.minimo else "completo" if args.completo else "interativo"
    escolhidos = escolher_grupos(modo)

    if escolhidos:
        titulo("Recursos opcionais")
        for chave in escolhidos:
            grupo_dados = GRUPOS[chave]
            instalar(python, grupo_dados["pacotes"], grupo_dados["titulo"])
        if "ocr" in escolhidos:
            verificar_tesseract()

    titulo("Banco de dados")
    inicializar_banco(python)

    comando = (
        ".venv\\Scripts\\python start.py"
        if os.name == "nt" and not args.sem_venv
        else ".venv/bin/python start.py"
        if not args.sem_venv
        else "python start.py"
    )

    titulo("Instalação concluída")
    print(
        f"  Inicie o servidor com:\n\n"
        f"      {comando}\n\n"
        f"  E abra http://127.0.0.1:8080 no navegador.\n\n"
        f"  Outras opções:\n"
        f"      {comando} --navegador     abre o navegador automaticamente\n"
        f"      {comando} --desktop       janela do aplicativo (requer PySide6)\n"
        f"      {comando} --host 0.0.0.0  acessível na rede local\n"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n  Instalação cancelada.")
        sys.exit(130)
