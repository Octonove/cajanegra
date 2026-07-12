"""El corazon de CajaNegra: un buffer CIRCULAR de capturas de pantalla que vive
SOLO en memoria RAM.

Privacidad por diseno:
  - Nada se escribe en disco mientras se vigila: los fotogramas viven en RAM y
    los antiguos se descartan solos al superar la edad del buffer.
  - NO hay audio continuo: la unica grabacion de voz posible es la nota de 30 s
    que el usuario decide grabar AL REPORTAR un incidente (ver voice.py).
  - Al cerrar la app, el buffer desaparece con el proceso.

Se captura el ESCRITORIO COMPLETO (todas las pantallas) y cada fotograma se
reescala para que su lado MAYOR no pase de MAX_LADO: la RAM queda acotada
tambien con monitores en vertical o varios monitores. Ademas el anillo tiene un
tope duro en bytes como valvula de seguridad.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_LADO = 1600            # lado MAYOR maximo del fotograma reescalado
MAX_BYTES = 500 * 1024**2  # valvula de seguridad del anillo (500 MB)
MAX_FALLOS = 5             # fallos seguidos de captura antes de recrear mss


@dataclass
class Frame:
    ts: float            # time.time() de la captura
    jpeg: bytes          # fotograma comprimido (JPEG)


class FrameRing:
    """Anillo de fotogramas acotado por EDAD (segundos) y por BYTES. Logica pura
    y testeable: no sabe nada de pantallas ni de hilos (el lock lo pone quien
    lo usa). El contador de bytes es incremental (sin sum() O(n))."""

    def __init__(self, max_age_s: float, max_bytes: int = MAX_BYTES):
        self.max_age_s = float(max_age_s)
        self.max_bytes = int(max_bytes)
        self._frames: deque[Frame] = deque()
        self._bytes = 0

    def add(self, frame: Frame) -> None:
        self._frames.append(frame)
        self._bytes += len(frame.jpeg)
        self._evict(frame.ts)

    def _evict(self, now: float) -> None:
        limite = now - self.max_age_s
        while self._frames and (self._frames[0].ts < limite or self._bytes > self.max_bytes):
            viejo = self._frames.popleft()
            self._bytes -= len(viejo.jpeg)

    def snapshot(self) -> list[Frame]:
        """Copia inmutable del contenido actual (para congelar un incidente)."""
        return list(self._frames)

    def set_max_age(self, max_age_s: float) -> None:
        self.max_age_s = float(max_age_s)
        if self._frames:
            self._evict(self._frames[-1].ts)

    @property
    def count(self) -> int:
        return len(self._frames)

    @property
    def seconds(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        return self._frames[-1].ts - self._frames[0].ts

    @property
    def bytes_used(self) -> int:
        return self._bytes


class BlackBox:
    """Hilo de captura: cada 1/fps segundos toma el escritorio con mss, lo
    reescala y lo comprime a JPEG en el anillo. Best-effort con autocuracion:
    si la captura falla varias veces seguidas (monitor desconectado, RDP,
    cambio de resolucion), recrea mss; si aun asi falla, publica self.error
    para que la UI lo muestre en vez de fingir que vigila."""

    def __init__(self, *, minutos: int = 3, fps: int = 1):
        self.ring = FrameRing(max(1, min(10, int(minutos))) * 60)
        self.fps = max(1, min(2, int(fps)))
        self._lock = threading.Lock()
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        # Evento PROPIO de este arranque: un hilo antiguo atascado (join expirado)
        # observa SU evento, que queda puesto para siempre — no puede resucitar
        # aunque se vuelva a arrancar (antes, _stop.clear() revivia al zombi).
        stop_evt = threading.Event()
        self._stop = stop_evt
        self.error = None
        self._thread = threading.Thread(target=self._run, args=(stop_evt,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        t = self._thread
        if t:
            t.join(timeout=3)
            if t.is_alive():
                logger.warning("El hilo de captura no termino en 3s (seguira "
                               "parandose solo; su evento de stop queda puesto).")
        self._thread = None

    def clear(self) -> None:
        with self._lock:
            self.ring = FrameRing(self.ring.max_age_s, self.ring.max_bytes)

    def set_minutos(self, minutos: int) -> None:
        with self._lock:
            self.ring.set_max_age(max(1, min(10, int(minutos))) * 60)

    def set_fps(self, fps: int) -> None:
        """Aplica en vivo: el bucle lee self.fps en cada iteracion. No se pierde
        el buffer (antes se recreaba el objeto entero y se descartaba todo)."""
        self.fps = max(1, min(2, int(fps)))

    def snapshot(self) -> list[Frame]:
        with self._lock:
            return self.ring.snapshot()

    def stats(self) -> tuple[int, float, float]:
        """(fotogramas, segundos cubiertos, MB en RAM)."""
        with self._lock:
            return self.ring.count, self.ring.seconds, self.ring.bytes_used / 1024**2

    # ------------------------------------------------------------- captura
    def _abrir_mss(self):
        import mss
        return mss.mss()

    def _run(self, stop_evt: threading.Event) -> None:
        try:
            import io
            from PIL import Image
        except Exception as exc:  # noqa: BLE001
            self.error = f"Captura no disponible (Pillow): {exc}"
            logger.warning(self.error)
            return
        sct = None
        fallos = 0
        try:
            while not stop_evt.is_set():
                t0 = time.time()
                try:
                    if sct is None:
                        sct = self._abrir_mss()
                    mon = sct.monitors[0]      # escritorio completo (todas las pantallas)
                    grab = sct.grab(mon)
                    img = Image.frombytes("RGB", grab.size, grab.bgra, "raw", "BGRX")
                    # bound por el lado MAYOR: monitores verticales incluidos
                    if max(img.width, img.height) > MAX_LADO:
                        img.thumbnail((MAX_LADO, MAX_LADO))
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=60)
                    if stop_evt.is_set():
                        break                   # no anadir tras un stop (privacidad)
                    with self._lock:
                        self.ring.add(Frame(ts=t0, jpeg=buf.getvalue()))
                    if fallos:
                        fallos = 0
                        self.error = None       # recuperado: limpiar el aviso
                except Exception as exc:  # noqa: BLE001
                    fallos += 1
                    if fallos == 1:
                        logger.warning("captura fallo: %s", exc)
                    if fallos >= MAX_FALLOS:
                        # reintento con instancia nueva (re-enumera monitores tras
                        # dock/undock, RDP o cambio de resolucion)
                        try:
                            if sct is not None:
                                sct.close()
                        except Exception:  # noqa: BLE001
                            pass
                        sct = None
                        self.error = ("La captura de pantalla esta fallando "
                                      "(¿monitor desconectado o sesion bloqueada?). "
                                      "Reintentando…")
                resto = (1.0 / self.fps) - (time.time() - t0)
                if resto > 0:
                    stop_evt.wait(resto)
        finally:
            try:
                if sct is not None:
                    sct.close()
            except Exception:  # noqa: BLE001
                pass
