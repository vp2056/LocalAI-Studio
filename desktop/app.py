"""
Aplicativo desktop do LocalAI Studio (PySide6).

Sobe o servidor Uvicorn em uma thread e abre a interface web em uma janela
nativa com QWebEngineView. É a mesma aplicação do modo servidor — sem
duplicação de código de interface.

Uso:
    python start.py --desktop
    python desktop/app.py
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

# Permite executar este arquivo diretamente.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

logger = logging.getLogger(__name__)

# Tempo máximo de espera pelo servidor antes de desistir.
TIMEOUT_SERVIDOR = 40


def _servidor_no_ar(host: str, porta: int) -> bool:
    """Verifica se o endpoint de saúde já responde."""
    import urllib.error
    import urllib.request

    alvo = "127.0.0.1" if host == "0.0.0.0" else host
    try:
        with urllib.request.urlopen(
            f"http://{alvo}:{porta}/api/health", timeout=1
        ) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _iniciar_servidor(host: str, porta: int) -> threading.Thread:
    """Sobe o Uvicorn em uma thread de fundo (daemon)."""
    import uvicorn

    def executar() -> None:
        uvicorn.run(
            "backend.main:app",
            host=host,
            port=porta,
            log_config=None,
            access_log=False,
        )

    thread = threading.Thread(target=executar, daemon=True, name="servidor-uvicorn")
    thread.start()
    return thread


def iniciar_desktop(host: str = "127.0.0.1", porta: int = 8080) -> int:
    """Abre a janela do aplicativo. Retorna o código de saída."""
    try:
        from PySide6.QtCore import QUrl, Qt
        from PySide6.QtGui import QIcon, QKeySequence, QShortcut
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
    except ImportError:
        print(
            "\n  O modo desktop requer PySide6.\n"
            "  Instale com:  pip install PySide6\n\n"
            "  Alternativa: use 'python start.py --navegador' para abrir no navegador.\n"
        )
        return 1

    from backend.config import settings

    _iniciar_servidor(host, porta)

    print("  Iniciando servidor…")
    limite = time.time() + TIMEOUT_SERVIDOR
    while not _servidor_no_ar(host, porta):
        if time.time() > limite:
            print("  O servidor não respondeu a tempo. Verifique os logs.")
            return 1
        time.sleep(0.4)

    app = QApplication(sys.argv)
    app.setApplicationName(settings.app_name)
    app.setOrganizationName("LocalAI Studio")

    icone = settings.caminho("frontend") / "assets" / "icone.png"
    if icone.exists():
        app.setWindowIcon(QIcon(str(icone)))

    janela = QMainWindow()
    janela.setWindowTitle(f"{settings.app_name} {settings.version}")
    janela.resize(1360, 880)
    janela.setMinimumSize(900, 620)

    navegador = QWebEngineView()
    navegador.setUrl(QUrl(f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{porta}"))
    janela.setCentralWidget(navegador)

    # Atalhos equivalentes aos de um navegador.
    QShortcut(QKeySequence("Ctrl+R"), janela, navegador.reload)
    QShortcut(QKeySequence("F5"), janela, navegador.reload)
    QShortcut(QKeySequence("Ctrl+Q"), janela, app.quit)
    QShortcut(
        QKeySequence("F11"),
        janela,
        lambda: janela.showNormal() if janela.isFullScreen() else janela.showFullScreen(),
    )

    def falha_no_carregamento(ok: bool) -> None:
        if not ok:
            QMessageBox.warning(
                janela,
                "Falha ao carregar",
                "A interface não pôde ser carregada.\n"
                "Verifique se o servidor está em execução e tente recarregar (Ctrl+R).",
            )

    navegador.loadFinished.connect(falha_no_carregamento)

    janela.show()
    print(f"  Janela aberta em http://{host}:{porta}")
    return app.exec()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(iniciar_desktop())
