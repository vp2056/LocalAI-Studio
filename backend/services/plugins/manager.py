"""
Sistema de plugins.

Um plugin é um diretório em ``plugins/`` contendo:

    meu_plugin/
        plugin.json     — manifesto (obrigatório)
        __init__.py     — código com as funções de gancho

Manifesto mínimo::

    {
      "slug": "meu_plugin",
      "name": "Meu Plugin",
      "version": "1.0.0",
      "author": "Você",
      "description": "O que ele faz",
      "hooks": ["on_message", "on_response"],
      "permissions": []
    }

Ganchos suportados:
  ``on_startup(contexto)``            – ao iniciar o servidor;
  ``on_shutdown(contexto)``           – ao encerrar;
  ``on_message(texto, **ctx) -> str`` – transforma a entrada do usuário;
  ``on_response(texto, **ctx) -> str``– transforma a resposta do modelo;
  ``on_document(documento, **ctx)``   – após indexar um documento.

Isolamento: plugins rodam no mesmo processo (requisito de simplicidade e
desempenho offline), portanto só devem ser instalados a partir de fontes
confiáveis. Toda exceção de plugin é capturada e registrada — um plugin
defeituoso nunca derruba o servidor nem interrompe uma conversa.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ...config import settings
from ...core.exceptions import PluginError
from ...database.models import Plugin
from ...database.session import sessao

logger = logging.getLogger(__name__)

MANIFESTO = "plugin.json"
GANCHOS_VALIDOS = {
    "on_startup",
    "on_shutdown",
    "on_message",
    "on_response",
    "on_document",
}
CAMPOS_OBRIGATORIOS = ("slug", "name", "version")


class GerenciadorPlugins:
    """Descoberta, instalação e execução de plugins."""

    def __init__(self) -> None:
        # slug -> módulo carregado
        self._modulos: dict[str, Any] = {}

    @property
    def diretorio(self) -> Path:
        return settings.caminho("plugins")

    # ---------------------------------------------------------- descoberta
    def escanear(self) -> list[dict[str, Any]]:
        """Varre a pasta de plugins e sincroniza os manifestos com o banco."""
        encontrados: list[dict[str, Any]] = []

        for pasta in sorted(p for p in self.diretorio.iterdir() if p.is_dir()):
            if pasta.name.startswith((".", "_")):
                continue
            arquivo = pasta / MANIFESTO
            if not arquivo.exists():
                continue
            try:
                manifesto = self._ler_manifesto(arquivo)
                manifesto["path"] = str(pasta)
                encontrados.append(manifesto)
            except PluginError as exc:
                logger.warning("Plugin inválido em %s: %s", pasta.name, exc)

        self._sincronizar(encontrados)
        return encontrados

    def _ler_manifesto(self, arquivo: Path) -> dict[str, Any]:
        """Lê e valida um plugin.json."""
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PluginError(f"{MANIFESTO} inválido: {exc}") from exc

        faltando = [c for c in CAMPOS_OBRIGATORIOS if not dados.get(c)]
        if faltando:
            raise PluginError(f"Campos obrigatórios ausentes: {', '.join(faltando)}")

        ganchos = dados.get("hooks", [])
        desconhecidos = set(ganchos) - GANCHOS_VALIDOS
        if desconhecidos:
            raise PluginError(f"Ganchos desconhecidos: {', '.join(desconhecidos)}")

        return dados

    def _sincronizar(self, manifestos: list[dict[str, Any]]) -> None:
        """Atualiza a tabela ``plugins`` conforme o que existe em disco."""
        with sessao() as db:
            registrados = {p.slug: p for p in db.scalars(select(Plugin)).all()}
            slugs_em_disco = {m["slug"] for m in manifestos}

            for manifesto in manifestos:
                registro = registrados.get(manifesto["slug"])
                campos = {
                    "name": manifesto["name"],
                    "version": manifesto["version"],
                    "author": manifesto.get("author"),
                    "description": manifesto.get("description"),
                    "homepage": manifesto.get("homepage"),
                    "path": manifesto["path"],
                    "hooks": manifesto.get("hooks", []),
                    "permissions": manifesto.get("permissions", []),
                    "installed": True,
                }
                if registro is None:
                    db.add(Plugin(slug=manifesto["slug"], enabled=False, **campos))
                    logger.info("Plugin descoberto: %s", manifesto["name"])
                else:
                    for chave, valor in campos.items():
                        setattr(registro, chave, valor)

            # Plugins removidos manualmente da pasta.
            for slug, registro in registrados.items():
                if slug not in slugs_em_disco and registro.installed:
                    registro.installed = False
                    registro.enabled = False

    # ----------------------------------------------------------- carga
    def carregar_ativos(self) -> int:
        """Importa os módulos de todos os plugins habilitados."""
        with sessao() as db:
            ativos = db.scalars(
                select(Plugin).where(
                    Plugin.enabled.is_(True), Plugin.installed.is_(True)
                )
            ).all()
            dados = [(p.slug, p.path) for p in ativos]

        carregados = 0
        for slug, caminho in dados:
            if self._importar(slug, Path(caminho)):
                carregados += 1
        logger.info("Plugins carregados: %d", carregados)
        return carregados

    def _importar(self, slug: str, caminho: Path) -> bool:
        """Importa o módulo de um plugin, registrando erros no banco."""
        if slug in self._modulos:
            return True

        entrada = caminho / "__init__.py"
        if not entrada.exists():
            self._marcar_erro(slug, "Arquivo __init__.py ausente.")
            return False

        try:
            nome_modulo = f"lais_plugin_{slug}"
            spec = importlib.util.spec_from_file_location(nome_modulo, entrada)
            if spec is None or spec.loader is None:
                raise PluginError("Não foi possível preparar o módulo.")

            modulo = importlib.util.module_from_spec(spec)
            sys.modules[nome_modulo] = modulo
            spec.loader.exec_module(modulo)

            self._modulos[slug] = modulo
            self._marcar_erro(slug, None)
            logger.info("Plugin '%s' carregado.", slug)
            return True
        except Exception as exc:
            logger.exception("Falha ao carregar o plugin '%s'", slug)
            self._marcar_erro(slug, str(exc)[:2000])
            sys.modules.pop(f"lais_plugin_{slug}", None)
            return False

    def descarregar(self, slug: str) -> None:
        """Remove o módulo da memória (efetivo no próximo carregamento)."""
        self._modulos.pop(slug, None)
        sys.modules.pop(f"lais_plugin_{slug}", None)

    def _marcar_erro(self, slug: str, erro: str | None) -> None:
        with sessao() as db:
            registro = db.scalar(select(Plugin).where(Plugin.slug == slug))
            if registro:
                registro.error = erro
                if erro:
                    registro.enabled = False

    # -------------------------------------------------------- habilitação
    def habilitar(self, slug: str) -> Plugin:
        with sessao() as db:
            registro = db.scalar(select(Plugin).where(Plugin.slug == slug))
            if registro is None:
                raise PluginError(f"Plugin '{slug}' não encontrado.")
            if not registro.installed:
                raise PluginError(f"Plugin '{slug}' não está instalado.")
            caminho = Path(registro.path)

        if not self._importar(slug, caminho):
            raise PluginError(f"Não foi possível carregar o plugin '{slug}'.")

        with sessao() as db:
            registro = db.scalar(select(Plugin).where(Plugin.slug == slug))
            registro.enabled = True  # type: ignore[union-attr]
            db.flush()
            return registro  # type: ignore[return-value]

    def desabilitar(self, slug: str) -> Plugin:
        self.descarregar(slug)
        with sessao() as db:
            registro = db.scalar(select(Plugin).where(Plugin.slug == slug))
            if registro is None:
                raise PluginError(f"Plugin '{slug}' não encontrado.")
            registro.enabled = False
            db.flush()
            return registro

    # --------------------------------------------------------- instalação
    def instalar_zip(self, arquivo_zip: str | Path) -> dict[str, Any]:
        """
        Instala um plugin a partir de um arquivo .zip.

        Rejeita entradas com caminho absoluto ou ``..`` (travessia de diretório),
        que permitiriam escrever fora da pasta de plugins.
        """
        arquivo_zip = Path(arquivo_zip)
        if not zipfile.is_zipfile(arquivo_zip):
            raise PluginError("O arquivo enviado não é um .zip válido.")

        destino_temp = settings.caminho("temp") / f"plugin_{arquivo_zip.stem}"
        if destino_temp.exists():
            shutil.rmtree(destino_temp)

        with zipfile.ZipFile(arquivo_zip) as z:
            for membro in z.namelist():
                caminho = Path(membro)
                if caminho.is_absolute() or ".." in caminho.parts:
                    raise PluginError(f"Caminho inseguro no pacote: {membro}")
            z.extractall(destino_temp)

        # O manifesto pode estar na raiz do zip ou dentro de uma única pasta.
        raiz = destino_temp
        if not (raiz / MANIFESTO).exists():
            subpastas = [p for p in destino_temp.iterdir() if p.is_dir()]
            if len(subpastas) == 1 and (subpastas[0] / MANIFESTO).exists():
                raiz = subpastas[0]
            else:
                shutil.rmtree(destino_temp, ignore_errors=True)
                raise PluginError(f"{MANIFESTO} não encontrado no pacote.")

        try:
            manifesto = self._ler_manifesto(raiz / MANIFESTO)
        except PluginError:
            shutil.rmtree(destino_temp, ignore_errors=True)
            raise

        slug = manifesto["slug"]
        if not slug.replace("_", "").replace("-", "").isalnum():
            shutil.rmtree(destino_temp, ignore_errors=True)
            raise PluginError("O 'slug' deve conter apenas letras, números, _ e -.")

        destino_final = self.diretorio / slug
        if destino_final.exists():
            shutil.rmtree(destino_final)
        shutil.move(str(raiz), str(destino_final))
        shutil.rmtree(destino_temp, ignore_errors=True)

        self.escanear()
        logger.info("Plugin '%s' instalado.", manifesto["name"])
        return manifesto

    def remover(self, slug: str) -> None:
        """Desinstala um plugin, apagando seus arquivos."""
        self.desabilitar(slug)
        with sessao() as db:
            registro = db.scalar(select(Plugin).where(Plugin.slug == slug))
            if registro is None:
                raise PluginError(f"Plugin '{slug}' não encontrado.")
            caminho = Path(registro.path)
            db.delete(registro)

        # Confirma que o caminho está de fato dentro da pasta de plugins.
        try:
            caminho.resolve().relative_to(self.diretorio.resolve())
        except ValueError:
            raise PluginError("Caminho do plugin fora do diretório permitido.")

        if caminho.exists():
            shutil.rmtree(caminho, ignore_errors=True)
        logger.info("Plugin '%s' removido.", slug)

    # ------------------------------------------------------------ execução
    def executar_gancho(self, gancho: str, valor: Any = None, **contexto: Any) -> Any:
        """
        Aciona um gancho em todos os plugins ativos, encadeando o valor.

        Ganchos transformadores (``on_message``, ``on_response``) recebem o
        valor produzido pelo plugin anterior. Um plugin que devolve ``None``
        ou lança exceção é ignorado, preservando o valor original.
        """
        for slug, modulo in list(self._modulos.items()):
            funcao = getattr(modulo, gancho, None)
            if not callable(funcao):
                continue
            try:
                resultado = (
                    funcao(valor, **contexto) if valor is not None else funcao(**contexto)
                )
                if resultado is not None:
                    valor = resultado
            except Exception:
                logger.exception("Erro no gancho '%s' do plugin '%s'", gancho, slug)
        return valor

    # --------------------------------------------------------- marketplace
    def marketplace(self) -> list[dict[str, Any]]:
        """
        Catálogo local de plugins disponíveis para instalação.

        Lê ``plugins/_marketplace/catalogo.json`` — um arquivo mantido offline
        pelo usuário ou distribuído junto com a instalação.
        """
        catalogo = self.diretorio / "_marketplace" / "catalogo.json"
        if not catalogo.exists():
            return []
        try:
            dados = json.loads(catalogo.read_text(encoding="utf-8"))
            itens = dados.get("plugins", dados) if isinstance(dados, dict) else dados
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Catálogo do marketplace ilegível: %s", exc)
            return []

        with sessao() as db:
            instalados = {p.slug for p in db.scalars(select(Plugin)).all()}

        for item in itens:
            item["installed"] = item.get("slug") in instalados
        return itens

    def estado(self) -> dict[str, Any]:
        with sessao() as db:
            todos = db.scalars(select(Plugin)).all()
            return {
                "total": len(todos),
                "enabled": sum(1 for p in todos if p.enabled),
                "loaded": len(self._modulos),
                "with_errors": sum(1 for p in todos if p.error),
            }


# Instância única.
gerenciador_plugins = GerenciadorPlugins()
