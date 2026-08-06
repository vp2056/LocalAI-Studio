#!/usr/bin/env python3
"""
Inicializador do LocalAI Studio.

Uso:
    python start.py                       # servidor local (127.0.0.1:8080)
    python start.py --host 0.0.0.0        # acessível na rede local
    python start.py --port 9000 --reload  # desenvolvimento
    python start.py --desktop             # abre a janela do aplicativo
    python start.py --sem-auth            # usuário único, sem login
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Executável empacotado (PyInstaller): o código já vem embutido no bundle.
CONGELADO = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

# Garante que o pacote ``backend`` seja importável ao rodar de qualquer lugar.
if not CONGELADO:
    RAIZ = Path(__file__).resolve().parent
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))

BANNER = r"""
  _                    _   _    ___   ____  _             _ _
 | |    ___   ___ __ _| | / \  |_ _| / ___|| |_ _   _  __| (_) ___
 | |   / _ \ / __/ _` | |/ _ \  | |  \___ \| __| | | |/ _` | |/ _ \
 | |__| (_) | (_| (_| | / ___ \ | |   ___) | |_| |_| | (_| | | (_) |
 |_____\___/ \___\__,_|_/_/   \_\___| |____/ \__|\__,_|\__,_|_|\___/

  Inteligência Artificial local — 100% offline
"""


def analisar_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inicia o LocalAI Studio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default=None, help="Endereço de escuta")
    parser.add_argument("--port", type=int, default=None, help="Porta")
    parser.add_argument("--reload", action="store_true", help="Recarga automática")
    parser.add_argument("--debug", action="store_true", help="Modo de depuração")
    parser.add_argument(
        "--desktop", action="store_true", help="Abre a janela do aplicativo (PySide6)"
    )
    parser.add_argument(
        "--navegador", action="store_true", help="Abre o navegador ao iniciar"
    )
    parser.add_argument(
        "--sem-auth",
        action="store_true",
        help="Desativa a autenticação (usuário único, uso local)",
    )
    parser.add_argument(
        "--portatil",
        action="store_true",
        help="Modo portátil: dados ficam na pasta do projeto",
    )
    return parser.parse_args()


def porta_livre(host: str, porta: int) -> bool:
    """Verifica se a porta está disponível."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", porta)) != 0


def proxima_porta_livre(host: str, inicial: int, tentativas: int = 20) -> int:
    """Procura a primeira porta livre a partir da inicial."""
    for porta in range(inicial, inicial + tentativas):
        if porta_livre(host, porta):
            return porta
    raise SystemExit(
        f"Nenhuma porta livre entre {inicial} e {inicial + tentativas - 1}."
    )


def ip_local() -> str:
    """Descobre o IP da máquina na rede local (para o modo servidor)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Não há tráfego real: apenas força o SO a escolher a interface.
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def abrir_navegador(url: str, atraso: float = 1.8) -> None:
    """Abre o navegador padrão após o servidor subir."""

    def tarefa() -> None:
        time.sleep(atraso)
        try:
            webbrowser.open(url)
        except Exception:
            pass  # ambiente sem navegador (servidor headless)

    threading.Thread(target=tarefa, daemon=True).start()


def main() -> None:
    args = analisar_argumentos()

    # As variáveis de ambiente precisam existir antes de importar a config.
    if args.debug:
        os.environ["LAIS_DEBUG"] = "true"
        os.environ["LAIS_LOG_LEVEL"] = "DEBUG"
    if args.sem_auth:
        os.environ["LAIS_AUTH_REQUIRED"] = "false"
        os.environ["LAIS_CSRF_ENABLED"] = "false"
    if args.portatil:
        os.environ["LAIS_MODE"] = "portable"
    if args.desktop:
        os.environ["LAIS_MODE"] = "desktop"

    from backend.config import settings

    host = args.host or settings.host
    porta = args.port or settings.port

    if not porta_livre(host, porta):
        nova = proxima_porta_livre(host, porta + 1)
        print(f"  Porta {porta} ocupada; usando {nova}.")
        porta = nova

    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{porta}"

    print(BANNER)
    print(f"  Versão:    {settings.version}")
    print(f"  Interface: {url}")
    if host == "0.0.0.0":
        print(f"  Na rede:   http://{ip_local()}:{porta}")
    print(f"  API docs:  {url}/api/docs")
    print(f"  Dados:     {settings.base_dir}")
    if not settings.auth_required:
        print("  Atenção:   autenticação DESATIVADA (uso local apenas)")
    print()

    if args.desktop:
        # A janela do desktop sobe o servidor internamente.
        from desktop.app import iniciar_desktop

        iniciar_desktop(host=host, porta=porta)
        return

    if args.navegador:
        abrir_navegador(url)

    import uvicorn

    # A recarga automática exige reexecutar o interpretador com o código-fonte,
    # o que não existe dentro de um executável empacotado.
    recarregar = args.reload and not CONGELADO
    if args.reload and CONGELADO:
        print("  --reload não é suportado no executável empacotado; ignorando.")

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=porta,
        reload=recarregar,
        log_config=None,  # o logging já é configurado pela aplicação
        access_log=False,  # substituído pelo RequestLogMiddleware
        ws_ping_interval=25,
        ws_ping_timeout=60,
    )


if __name__ == "__main__":
    # Sem isto, cada processo-filho reexecutaria o programa inteiro no bundle.
    multiprocessing.freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Encerrado pelo usuário.")
