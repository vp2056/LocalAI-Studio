"""
Backup e restauração.

Um backup é um .zip contendo o banco SQLite (copiado de forma consistente com
a API de backup do próprio SQLite), as configurações, os plugins e,
opcionalmente, os documentos. Modelos nunca entram: são grandes e
re-obteníveis.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ...config import settings
from ...core.exceptions import ArquivoInvalido, RecursoNaoEncontrado

logger = logging.getLogger(__name__)

NOME_MANIFESTO = "backup.json"
PREFIXO = "localai_backup_"


class ServicoBackup:
    """Criação, listagem, restauração e expurgo de backups."""

    @property
    def diretorio(self) -> Path:
        return settings.caminho("backups")

    # ------------------------------------------------------------- criação
    def criar(self, *, incluir_documentos: bool = True, rotulo: str | None = None) -> Path:
        """Gera um novo arquivo de backup e devolve seu caminho."""
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
        sufixo = f"_{_higienizar(rotulo)}" if rotulo else ""
        destino = self.diretorio / f"{PREFIXO}{carimbo}{sufixo}.zip"

        temporario = settings.caminho("temp") / f"db_backup_{carimbo}.sqlite3"

        try:
            self._copiar_banco(temporario)

            with zipfile.ZipFile(
                destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6
            ) as z:
                z.write(temporario, "database/localai_studio.db")

                self._adicionar_pasta(z, settings.caminho("config"), "config")
                self._adicionar_pasta(
                    z, settings.caminho("plugins"), "plugins", ignorar={"__pycache__"}
                )
                if incluir_documentos:
                    self._adicionar_pasta(z, settings.caminho("documents"), "documents")

                manifesto = {
                    "app": settings.app_name,
                    "version": settings.version,
                    "created_at": datetime.now().isoformat(),
                    "includes_documents": incluir_documentos,
                    "label": rotulo,
                }
                z.writestr(
                    NOME_MANIFESTO, json.dumps(manifesto, indent=2, ensure_ascii=False)
                )
        finally:
            temporario.unlink(missing_ok=True)

        logger.info(
            "Backup criado: %s (%.1f MB)",
            destino.name,
            destino.stat().st_size / 1024 / 1024,
        )
        self.expurgar()
        return destino

    def _copiar_banco(self, destino: Path) -> None:
        """
        Copia o SQLite com a API de backup nativa.

        Copiar o arquivo diretamente enquanto há escritas em andamento
        produziria uma cópia corrompida; a API de backup garante consistência.
        """
        origem = settings.database_url.replace("sqlite:///", "")
        conexao_origem = sqlite3.connect(origem)
        conexao_destino = sqlite3.connect(destino)
        try:
            conexao_origem.backup(conexao_destino)
        finally:
            conexao_destino.close()
            conexao_origem.close()

    def _adicionar_pasta(
        self,
        z: zipfile.ZipFile,
        pasta: Path,
        prefixo: str,
        ignorar: set[str] | None = None,
    ) -> None:
        """Adiciona recursivamente o conteúdo de uma pasta ao zip."""
        if not pasta.exists():
            return
        ignorar = ignorar or set()
        for arquivo in pasta.rglob("*"):
            if not arquivo.is_file():
                continue
            if any(parte in ignorar for parte in arquivo.parts):
                continue
            z.write(arquivo, f"{prefixo}/{arquivo.relative_to(pasta)}")

    # ------------------------------------------------------------ listagem
    def listar(self) -> list[dict[str, Any]]:
        """Backups existentes, do mais recente ao mais antigo."""
        itens: list[dict[str, Any]] = []
        for arquivo in self.diretorio.glob(f"{PREFIXO}*.zip"):
            estado = arquivo.stat()
            item = {
                "filename": arquivo.name,
                "size_bytes": estado.st_size,
                "size_mb": round(estado.st_size / 1024 / 1024, 2),
                "created_at": datetime.fromtimestamp(estado.st_mtime).isoformat(),
            }
            item.update(self._ler_manifesto(arquivo))
            itens.append(item)

        itens.sort(key=lambda i: i["created_at"], reverse=True)
        return itens

    def _ler_manifesto(self, arquivo: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(arquivo) as z:
                return json.loads(z.read(NOME_MANIFESTO))
        except Exception:
            return {"valid": False}

    # --------------------------------------------------------- restauração
    def restaurar(self, nome_arquivo: str, *, restaurar_documentos: bool = True) -> None:
        """
        Restaura um backup sobre a instalação atual.

        Antes de sobrescrever, um backup de segurança do estado atual é criado
        automaticamente — a restauração é destrutiva e deve ser reversível.
        """
        origem = self._resolver(nome_arquivo)

        if not zipfile.is_zipfile(origem):
            raise ArquivoInvalido("O arquivo de backup está corrompido.")

        logger.warning("Criando backup de segurança antes da restauração…")
        self.criar(rotulo="pre_restauracao")

        # Fecha as conexões: no Windows o arquivo não pode ser substituído
        # enquanto estiver aberto.
        from ...database.session import engine

        engine.dispose()

        destino_banco = Path(settings.database_url.replace("sqlite:///", ""))

        with zipfile.ZipFile(origem) as z:
            for membro in z.namelist():
                caminho = Path(membro)
                if caminho.is_absolute() or ".." in caminho.parts:
                    raise ArquivoInvalido(f"Caminho inseguro no backup: {membro}")

            for membro in z.namelist():
                if membro == NOME_MANIFESTO:
                    continue

                if membro.startswith("database/"):
                    with z.open(membro) as f, destino_banco.open("wb") as saida:
                        shutil.copyfileobj(f, saida)
                elif membro.startswith("config/"):
                    self._extrair(z, membro, settings.caminho("config"), "config/")
                elif membro.startswith("plugins/"):
                    self._extrair(z, membro, settings.caminho("plugins"), "plugins/")
                elif membro.startswith("documents/") and restaurar_documentos:
                    self._extrair(z, membro, settings.caminho("documents"), "documents/")

        logger.warning("Backup '%s' restaurado. Reinicie o servidor.", nome_arquivo)

    def _extrair(
        self, z: zipfile.ZipFile, membro: str, destino: Path, prefixo: str
    ) -> None:
        relativo = membro[len(prefixo) :]
        if not relativo:
            return
        alvo = destino / relativo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        with z.open(membro) as f, alvo.open("wb") as saida:
            shutil.copyfileobj(f, saida)

    # ------------------------------------------------------------ remoção
    def remover(self, nome_arquivo: str) -> None:
        self._resolver(nome_arquivo).unlink()
        logger.info("Backup removido: %s", nome_arquivo)

    def expurgar(self) -> int:
        """Mantém apenas os ``backup_keep`` backups mais recentes."""
        arquivos = sorted(
            self.diretorio.glob(f"{PREFIXO}*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        removidos = 0
        for antigo in arquivos[settings.backup_keep :]:
            antigo.unlink(missing_ok=True)
            removidos += 1
        if removidos:
            logger.info("Backups antigos removidos: %d", removidos)
        return removidos

    def _resolver(self, nome_arquivo: str) -> Path:
        """Valida o nome e devolve o caminho, impedindo travessia de diretório."""
        caminho = (self.diretorio / Path(nome_arquivo).name).resolve()
        try:
            caminho.relative_to(self.diretorio.resolve())
        except ValueError:
            raise ArquivoInvalido("Nome de arquivo inválido.")
        if not caminho.exists():
            raise RecursoNaoEncontrado(f"Backup '{nome_arquivo}' não encontrado.")
        return caminho


def _higienizar(texto: str) -> str:
    """Reduz um rótulo a caracteres seguros para nome de arquivo."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in texto)[:40]


# Instância única.
servico_backup = ServicoBackup()
