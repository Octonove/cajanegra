"""Nota de voz OPCIONAL al reportar un incidente (el 'testimonio' del dossier).

CajaNegra NO graba audio de forma continua: esta es la unica captura de audio
de la app, dura como maximo 30 s y solo ocurre cuando el usuario pulsa el boton.

REGLA COM de la suite: soundcard inicializa COM/MTA en el hilo que lo importa
por primera vez, y eso congela los dialogos nativos de Tk. Por eso se carga
perezosamente y SOLO dentro del hilo de grabacion (leccion de CapturaStudio).
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

SR = 16000          # suficiente para voz y lo que espera Whisper
BLOCK = 1024
MAX_SEG = 30.0

AVAILABLE = (importlib.util.find_spec("soundcard") is not None
             and importlib.util.find_spec("numpy") is not None)


class VoiceRecorder:
    """Graba el microfono por defecto a WAV, hasta MAX_SEG o hasta stop()."""

    def __init__(self, wav_path: str):
        self.wav_path = wav_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.ok = False
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running or not AVAILABLE:
            if not AVAILABLE:
                self.error = "Audio no disponible (falta soundcard/numpy)."
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        """Detiene y devuelve True si quedo un WAV utilizable."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        return self.ok

    def _run(self) -> None:
        # COM por-hilo + import perezoso: NUNCA en el hilo de la UI.
        import ctypes
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)
        except (AttributeError, OSError):
            pass
        try:
            import numpy as np
            import soundcard as sc
        except Exception as exc:  # noqa: BLE001
            self.error = f"Audio no disponible: {exc}"
            logger.warning(self.error)
            return
        rec = None
        try:
            mic = sc.default_microphone()
            # apertura robusta (leccion de CapturaStudio: los micros USB mono
            # rechazan configs exactas; probamos canales 1 y 2)
            last = None
            for ch in (1, 2):
                try:
                    rec = mic.recorder(samplerate=SR, channels=ch, blocksize=BLOCK)
                    rec.__enter__()
                    break
                except Exception as exc:  # noqa: BLE001
                    last, rec = exc, None
            if rec is None:
                raise last or RuntimeError("No se pudo abrir el microfono.")
            wf = wave.open(self.wav_path, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            grabados = 0
            try:
                while not self._stop.is_set() and grabados < SR * MAX_SEG:
                    data = rec.record(numframes=BLOCK)
                    if data.ndim > 1:
                        data = data.mean(axis=1)      # a mono
                    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                    wf.writeframes(pcm)
                    grabados += len(data)
            finally:
                wf.close()
            self.ok = Path(self.wav_path).is_file() and Path(self.wav_path).stat().st_size > 4096
        except Exception as exc:  # noqa: BLE001
            self.error = f"No se pudo grabar la nota de voz: {exc}"
            logger.warning(self.error)
            self.ok = False
        finally:
            if rec is not None:
                try:
                    rec.__exit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
            try:
                ctypes.windll.ole32.CoUninitialize()
            except (AttributeError, OSError):
                pass
