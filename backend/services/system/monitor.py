"""
Monitor de recursos: CPU, RAM, GPU, temperatura e disco.

A detecção de GPU tenta, em ordem: pynvml (NVIDIA), torch.cuda e o binário
``nvidia-smi``. Nenhuma dessas fontes é obrigatória — sem elas, a seção de GPU
simplesmente informa que não há placa detectada.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import time
from typing import Any

import psutil

from ...config import settings

logger = logging.getLogger(__name__)

GB = 1024**3

# Intervalo mínimo entre coletas completas (segundos). Chamadas mais
# frequentes recebem o último resultado em cache — o painel atualiza a cada
# segundo e não deve custar CPU só para se medir.
INTERVALO_CACHE = 0.9


class MonitorSistema:
    """Coleta métricas do computador."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] | None = None
        self._cache_em: float = 0.0
        self._inicio = time.time()
        # Primeira chamada a cpu_percent estabelece a linha de base.
        psutil.cpu_percent(interval=None)

    # ------------------------------------------------------------- coleta
    def coletar(self, forcar: bool = False) -> dict[str, Any]:
        """Métricas completas do sistema (com cache curto)."""
        agora = time.monotonic()
        if not forcar and self._cache and (agora - self._cache_em) < INTERVALO_CACHE:
            return self._cache

        dados = {
            "timestamp": time.time(),
            "uptime_seconds": int(time.time() - self._inicio),
            "platform": self._plataforma(),
            "cpu": self._cpu(),
            "memory": self._memoria(),
            "swap": self._swap(),
            "disk": self._disco(),
            "gpu": self._gpu(),
            "temperature": self._temperatura(),
            "process": self._processo(),
        }
        self._cache = dados
        self._cache_em = agora
        return dados

    def _plataforma(self) -> dict[str, Any]:
        return {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "hostname": platform.node(),
        }

    def _cpu(self) -> dict[str, Any]:
        frequencia = None
        try:
            info = psutil.cpu_freq()
            frequencia = round(info.current, 0) if info else None
        except (OSError, AttributeError):
            pass  # indisponível em alguns contêineres e ARM

        return {
            "percent": psutil.cpu_percent(interval=None),
            "per_core": psutil.cpu_percent(interval=None, percpu=True),
            "cores": psutil.cpu_count(logical=True) or 0,
            "physical_cores": psutil.cpu_count(logical=False) or 0,
            "frequency_mhz": frequencia,
            "load_average": self._carga(),
        }

    def _carga(self) -> list[float] | None:
        """Média de carga de 1/5/15 minutos (indisponível no Windows antigo)."""
        try:
            return [round(v, 2) for v in psutil.getloadavg()]
        except (AttributeError, OSError):
            return None

    def _memoria(self) -> dict[str, Any]:
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / GB, 2),
            "used_gb": round(mem.used / GB, 2),
            "available_gb": round(mem.available / GB, 2),
            "percent": mem.percent,
        }

    def _swap(self) -> dict[str, Any]:
        swap = psutil.swap_memory()
        return {
            "total_gb": round(swap.total / GB, 2),
            "used_gb": round(swap.used / GB, 2),
            "percent": swap.percent,
        }

    def _disco(self) -> dict[str, Any]:
        # Mede a partição onde o projeto está instalado, não a raiz do sistema.
        uso = shutil.disk_usage(settings.base_dir)
        return {
            "total_gb": round(uso.total / GB, 2),
            "used_gb": round(uso.used / GB, 2),
            "free_gb": round(uso.free / GB, 2),
            "percent": round(uso.used / uso.total * 100, 1) if uso.total else 0.0,
            "path": str(settings.base_dir),
        }

    def _processo(self) -> dict[str, Any]:
        proc = psutil.Process()
        with proc.oneshot():
            return {
                "pid": proc.pid,
                "memory_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
                "threads": proc.num_threads(),
                "cpu_percent": proc.cpu_percent(interval=None),
            }

    # ---------------------------------------------------------------- GPU
    def _gpu(self) -> dict[str, Any]:
        """Informações da GPU, tentando as fontes disponíveis em ordem."""
        for fonte in (self._gpu_nvml, self._gpu_torch, self._gpu_smi):
            try:
                resultado = fonte()
                if resultado:
                    return {"available": True, "devices": resultado}
            except Exception as exc:
                logger.debug("Fonte de GPU indisponível: %s", exc)
        return {"available": False, "devices": []}

    def _gpu_nvml(self) -> list[dict[str, Any]]:
        import pynvml

        pynvml.nvmlInit()
        try:
            dispositivos = []
            for i in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                memoria = pynvml.nvmlDeviceGetMemoryInfo(handle)
                utilizacao = pynvml.nvmlDeviceGetUtilizationRates(handle)
                nome = pynvml.nvmlDeviceGetName(handle)
                try:
                    temperatura = pynvml.nvmlDeviceGetTemperature(handle, 0)
                except Exception:
                    temperatura = None

                dispositivos.append(
                    {
                        "index": i,
                        "name": nome.decode() if isinstance(nome, bytes) else nome,
                        "memory_total_gb": round(memoria.total / GB, 2),
                        "memory_used_gb": round(memoria.used / GB, 2),
                        "memory_percent": round(memoria.used / memoria.total * 100, 1),
                        "utilization_percent": utilizacao.gpu,
                        "temperature_c": temperatura,
                        "source": "nvml",
                    }
                )
            return dispositivos
        finally:
            pynvml.nvmlShutdown()

    def _gpu_torch(self) -> list[dict[str, Any]]:
        import torch

        if not torch.cuda.is_available():
            return []
        dispositivos = []
        for i in range(torch.cuda.device_count()):
            propriedades = torch.cuda.get_device_properties(i)
            reservado = torch.cuda.memory_reserved(i)
            dispositivos.append(
                {
                    "index": i,
                    "name": propriedades.name,
                    "memory_total_gb": round(propriedades.total_memory / GB, 2),
                    "memory_used_gb": round(reservado / GB, 2),
                    "memory_percent": round(
                        reservado / propriedades.total_memory * 100, 1
                    ),
                    "utilization_percent": None,
                    "temperature_c": None,
                    "source": "torch",
                }
            )
        return dispositivos

    def _gpu_smi(self) -> list[dict[str, Any]]:
        if shutil.which("nvidia-smi") is None:
            return []

        saida = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if saida.returncode != 0:
            return []

        dispositivos = []
        for linha in saida.stdout.strip().splitlines():
            campos = [c.strip() for c in linha.split(",")]
            if len(campos) < 6:
                continue
            total_mb, usado_mb = float(campos[2]), float(campos[3])
            dispositivos.append(
                {
                    "index": int(campos[0]),
                    "name": campos[1],
                    "memory_total_gb": round(total_mb / 1024, 2),
                    "memory_used_gb": round(usado_mb / 1024, 2),
                    "memory_percent": round(usado_mb / total_mb * 100, 1)
                    if total_mb
                    else 0.0,
                    "utilization_percent": float(campos[4]),
                    "temperature_c": float(campos[5]),
                    "source": "nvidia-smi",
                }
            )
        return dispositivos

    # -------------------------------------------------------- temperatura
    def _temperatura(self) -> dict[str, Any]:
        """Sensores térmicos da CPU/placa (disponível sobretudo no Linux)."""
        try:
            sensores = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return {"available": False, "sensors": {}}

        if not sensores:
            return {"available": False, "sensors": {}}

        resumo: dict[str, Any] = {}
        for nome, leituras in sensores.items():
            valores = [l.current for l in leituras if l.current]
            if valores:
                resumo[nome] = {
                    "current": round(max(valores), 1),
                    "count": len(valores),
                }

        # A temperatura "principal" é a mais alta entre os sensores de CPU.
        principal = None
        for chave in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if chave in resumo:
                principal = resumo[chave]["current"]
                break
        if principal is None and resumo:
            principal = max(v["current"] for v in resumo.values())

        return {"available": True, "cpu_c": principal, "sensors": resumo}

    # ------------------------------------------------------------ resumo
    def resumo(self) -> dict[str, Any]:
        """Versão enxuta para atualizações frequentes do painel."""
        dados = self.coletar()
        gpu = dados["gpu"]["devices"][0] if dados["gpu"]["devices"] else None
        return {
            "cpu_percent": dados["cpu"]["percent"],
            "memory_percent": dados["memory"]["percent"],
            "memory_used_gb": dados["memory"]["used_gb"],
            "memory_total_gb": dados["memory"]["total_gb"],
            "disk_percent": dados["disk"]["percent"],
            "disk_free_gb": dados["disk"]["free_gb"],
            "gpu_percent": gpu["utilization_percent"] if gpu else None,
            "gpu_memory_percent": gpu["memory_percent"] if gpu else None,
            "temperature_c": dados["temperature"].get("cpu_c"),
            "uptime_seconds": dados["uptime_seconds"],
        }


# Instância única.
monitor = MonitorSistema()
