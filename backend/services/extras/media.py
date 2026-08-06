"""
Recursos extras de mídia: OCR, voz (STT/TTS) e geração de imagens.

Todos dependem de bibliotecas opcionais e pesadas. O padrão adotado aqui é
uniforme: cada serviço expõe ``disponivel()`` e, quando indisponível, lança
``BackendIndisponivel`` com a instrução exata de instalação — nunca falha em
silêncio nem impede o servidor de iniciar.
"""

from __future__ import annotations

import logging
import time
import uuid
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from ...config import settings
from ...core.exceptions import ArquivoInvalido, BackendIndisponivel

logger = logging.getLogger(__name__)


# ===========================================================================
# OCR — imagem/PDF digitalizado para texto
# ===========================================================================
class ServicoOCR:
    """Reconhecimento óptico de caracteres via Tesseract."""

    # Idiomas na ordem de tentativa (português primeiro).
    IDIOMAS = "por+eng"

    @staticmethod
    def disponivel() -> bool:
        import shutil

        return find_spec("pytesseract") is not None and shutil.which("tesseract") is not None

    def extrair(self, caminho: str | Path, idioma: str | None = None) -> dict[str, Any]:
        """Extrai texto de uma imagem ou de um PDF digitalizado."""
        if not settings.ocr_enabled:
            raise BackendIndisponivel("OCR está desabilitado nas configurações.")
        if not self.disponivel():
            raise BackendIndisponivel(
                "OCR requer o Tesseract e o pytesseract.\n"
                "  Linux:   sudo apt install tesseract-ocr tesseract-ocr-por\n"
                "  macOS:   brew install tesseract tesseract-lang\n"
                "  Windows: instale o Tesseract e adicione-o ao PATH\n"
                "  Depois:  pip install pytesseract Pillow"
            )

        import pytesseract
        from PIL import Image

        caminho = Path(caminho)
        if not caminho.exists():
            raise ArquivoInvalido(f"Arquivo não encontrado: {caminho.name}")

        inicio = time.perf_counter()

        if caminho.suffix.lower() == ".pdf":
            texto = self._ocr_pdf(caminho, idioma or self.IDIOMAS)
        else:
            with Image.open(caminho) as imagem:
                texto = pytesseract.image_to_string(imagem, lang=idioma or self.IDIOMAS)

        return {
            "text": texto.strip(),
            "chars": len(texto.strip()),
            "language": idioma or self.IDIOMAS,
            "duration_ms": int((time.perf_counter() - inicio) * 1000),
        }

    def _ocr_pdf(self, caminho: Path, idioma: str) -> str:
        """Converte cada página do PDF em imagem antes do OCR."""
        try:
            from pdf2image import convert_from_path
        except ImportError as exc:
            raise BackendIndisponivel(
                "OCR de PDF requer 'pdf2image' e o utilitário poppler. "
                "Execute: pip install pdf2image (e instale o poppler-utils)."
            ) from exc

        import pytesseract

        paginas = convert_from_path(str(caminho), dpi=200)
        partes = []
        for numero, imagem in enumerate(paginas, start=1):
            partes.append(
                f"[[página {numero}]]\n"
                + pytesseract.image_to_string(imagem, lang=idioma)
            )
        return "\n\n".join(partes)


# ===========================================================================
# Reconhecimento de voz (STT)
# ===========================================================================
class ServicoSTT:
    """Transcrição de áudio com faster-whisper."""

    def __init__(self) -> None:
        self._modelo = None
        # "base" equilibra qualidade e velocidade em CPU comum.
        self._tamanho = "base"

    @staticmethod
    def disponivel() -> bool:
        return find_spec("faster_whisper") is not None

    def transcrever(
        self, caminho: str | Path, *, idioma: str | None = "pt"
    ) -> dict[str, Any]:
        """Transcreve um arquivo de áudio para texto."""
        if not settings.stt_enabled:
            raise BackendIndisponivel(
                "Reconhecimento de voz está desabilitado nas configurações."
            )
        if not self.disponivel():
            raise BackendIndisponivel(
                "Reconhecimento de voz requer faster-whisper. "
                "Execute: pip install faster-whisper"
            )

        from faster_whisper import WhisperModel

        if self._modelo is None:
            logger.info("Carregando modelo de transcrição '%s'…", self._tamanho)
            # int8 reduz memória e acelera bastante em CPU.
            self._modelo = WhisperModel(
                self._tamanho,
                device="auto",
                compute_type="int8",
                download_root=str(settings.caminho("models") / "whisper"),
            )

        inicio = time.perf_counter()
        segmentos, info = self._modelo.transcribe(str(caminho), language=idioma)

        partes = []
        detalhes = []
        for segmento in segmentos:
            partes.append(segmento.text)
            detalhes.append(
                {
                    "start": round(segmento.start, 2),
                    "end": round(segmento.end, 2),
                    "text": segmento.text.strip(),
                }
            )

        return {
            "text": "".join(partes).strip(),
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration_s": round(info.duration, 2),
            "segments": detalhes,
            "processing_ms": int((time.perf_counter() - inicio) * 1000),
        }


# ===========================================================================
# Texto para voz (TTS)
# ===========================================================================
class ServicoTTS:
    """
    Síntese de fala offline.

    Tenta ``piper`` (qualidade alta, totalmente offline) e, na ausência dele,
    ``pyttsx3``, que usa os motores nativos do sistema operacional.
    """

    @staticmethod
    def disponivel() -> bool:
        import shutil

        return (
            find_spec("piper") is not None
            or shutil.which("piper") is not None
            or find_spec("pyttsx3") is not None
        )

    def sintetizar(self, texto: str, *, voz: str | None = None) -> Path:
        """Gera um arquivo .wav com a fala e devolve seu caminho."""
        if not settings.tts_enabled:
            raise BackendIndisponivel("Texto para voz está desabilitado.")
        if not texto.strip():
            raise ArquivoInvalido("Texto vazio.")

        destino = settings.caminho("temp") / f"tts_{uuid.uuid4().hex[:12]}.wav"

        if find_spec("pyttsx3") is not None:
            return self._pyttsx3(texto, destino, voz)
        if find_spec("piper") is not None:
            return self._piper(texto, destino, voz)

        raise BackendIndisponivel(
            "Texto para voz requer um motor de síntese.\n"
            "  Simples:    pip install pyttsx3\n"
            "  Qualidade:  pip install piper-tts (e baixe uma voz .onnx)"
        )

    def _pyttsx3(self, texto: str, destino: Path, voz: str | None) -> Path:
        import pyttsx3

        motor = pyttsx3.init()
        if voz:
            for disponivel in motor.getProperty("voices"):
                if voz.lower() in disponivel.name.lower():
                    motor.setProperty("voice", disponivel.id)
                    break
        motor.save_to_file(texto, str(destino))
        motor.runAndWait()
        return destino

    def _piper(self, texto: str, destino: Path, voz: str | None) -> Path:
        import wave

        from piper import PiperVoice

        caminho_voz = voz or self._voz_padrao()
        if caminho_voz is None:
            raise BackendIndisponivel(
                "Nenhuma voz do Piper encontrada. Baixe um arquivo .onnx de voz "
                f"para {settings.caminho('models') / 'vozes'}."
            )

        modelo = PiperVoice.load(caminho_voz)
        with wave.open(str(destino), "wb") as arquivo:
            modelo.synthesize(texto, arquivo)
        return destino

    def _voz_padrao(self) -> str | None:
        pasta = settings.caminho("models") / "vozes"
        if not pasta.exists():
            return None
        vozes = sorted(pasta.glob("*.onnx"))
        return str(vozes[0]) if vozes else None

    def vozes(self) -> list[dict[str, Any]]:
        """Lista as vozes disponíveis no sistema."""
        resultado: list[dict[str, Any]] = []
        try:
            import pyttsx3

            motor = pyttsx3.init()
            resultado.extend(
                {"id": v.id, "name": v.name, "engine": "pyttsx3"}
                for v in motor.getProperty("voices")
            )
        except Exception:
            pass

        pasta = settings.caminho("models") / "vozes"
        if pasta.exists():
            resultado.extend(
                {"id": str(v), "name": v.stem, "engine": "piper"}
                for v in sorted(pasta.glob("*.onnx"))
            )
        return resultado


# ===========================================================================
# Geração de imagens
# ===========================================================================
class ServicoImagens:
    """Geração de imagens com modelos de difusão locais."""

    def __init__(self) -> None:
        self._pipeline = None
        self._modelo_atual: str | None = None

    @staticmethod
    def disponivel() -> bool:
        return find_spec("diffusers") is not None and find_spec("torch") is not None

    def modelos(self) -> list[dict[str, Any]]:
        """Modelos de difusão presentes em ``models/imagens/``."""
        pasta = settings.caminho("models") / "imagens"
        if not pasta.exists():
            return []
        itens = []
        for candidato in sorted(pasta.iterdir()):
            eh_diretorio = candidato.is_dir() and (candidato / "model_index.json").exists()
            eh_arquivo = candidato.suffix.lower() in (".safetensors", ".ckpt")
            if eh_diretorio or eh_arquivo:
                itens.append(
                    {
                        "name": candidato.name,
                        "path": str(candidato),
                        "type": "diffusers" if eh_diretorio else "checkpoint",
                    }
                )
        return itens

    def gerar(
        self,
        prompt: str,
        *,
        modelo: str | None = None,
        prompt_negativo: str = "",
        largura: int = 512,
        altura: int = 512,
        passos: int = 25,
        escala: float = 7.5,
        semente: int | None = None,
    ) -> dict[str, Any]:
        """Gera uma imagem a partir de um prompt textual."""
        if not settings.image_generation_enabled:
            raise BackendIndisponivel("Geração de imagens está desabilitada.")
        if not self.disponivel():
            raise BackendIndisponivel(
                "Geração de imagens requer diffusers e torch. "
                "Execute: pip install diffusers torch transformers accelerate"
            )

        disponiveis = self.modelos()
        if not disponiveis:
            raise BackendIndisponivel(
                "Nenhum modelo de difusão encontrado. Coloque um modelo em "
                f"{settings.caminho('models') / 'imagens'}."
            )

        alvo = next(
            (m for m in disponiveis if m["name"] == modelo), disponiveis[0]
        )
        self._carregar(alvo)

        import torch

        gerador = None
        if semente is not None and semente >= 0:
            dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
            gerador = torch.Generator(device=dispositivo).manual_seed(semente)

        inicio = time.perf_counter()
        saida = self._pipeline(  # type: ignore[misc]
            prompt=prompt,
            negative_prompt=prompt_negativo or None,
            width=largura,
            height=altura,
            num_inference_steps=passos,
            guidance_scale=escala,
            generator=gerador,
        )

        destino = (
            settings.caminho("uploads") / f"imagem_{uuid.uuid4().hex[:12]}.png"
        )
        saida.images[0].save(destino)

        return {
            "path": str(destino),
            "filename": destino.name,
            "model": alvo["name"],
            "prompt": prompt,
            "width": largura,
            "height": altura,
            "steps": passos,
            "seed": semente,
            "duration_ms": int((time.perf_counter() - inicio) * 1000),
        }

    def _carregar(self, alvo: dict[str, Any]) -> None:
        """Carrega o pipeline de difusão, reaproveitando o já carregado."""
        if self._pipeline is not None and self._modelo_atual == alvo["name"]:
            return

        import torch
        from diffusers import StableDiffusionPipeline

        dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if dispositivo == "cuda" else torch.float32

        logger.info("Carregando modelo de imagem '%s' em %s…", alvo["name"], dispositivo)

        if alvo["type"] == "diffusers":
            pipeline = StableDiffusionPipeline.from_pretrained(
                alvo["path"], torch_dtype=dtype, local_files_only=True
            )
        else:
            pipeline = StableDiffusionPipeline.from_single_file(
                alvo["path"], torch_dtype=dtype, local_files_only=True
            )

        self._pipeline = pipeline.to(dispositivo)
        self._modelo_atual = alvo["name"]


# Instâncias únicas.
servico_ocr = ServicoOCR()
servico_stt = ServicoSTT()
servico_tts = ServicoTTS()
servico_imagens = ServicoImagens()


def estado_extras() -> dict[str, Any]:
    """Situação de cada recurso extra, para exibição na interface."""
    return {
        "ocr": {"available": ServicoOCR.disponivel(), "enabled": settings.ocr_enabled},
        "stt": {"available": ServicoSTT.disponivel(), "enabled": settings.stt_enabled},
        "tts": {"available": ServicoTTS.disponivel(), "enabled": settings.tts_enabled},
        "image_generation": {
            "available": ServicoImagens.disponivel(),
            "enabled": settings.image_generation_enabled,
            "models": len(servico_imagens.modelos()),
        },
    }
