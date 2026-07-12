"""Construccion del incidente: video MP4 desde el buffer, contexto del sistema
(eventos de Windows, procesos) y transcripcion opcional de la nota de voz."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

from octonove_core.ffmpeg import find_ffmpeg as _find_ffmpeg
from octonove_core.ffmpeg import has_whisper
from octonove_core.procutil import subprocess_kwargs

from .buffer import Frame
from .config import models_dir, work_dir

logger = logging.getLogger(__name__)


class IncidentError(Exception):
    pass


def find_ffmpeg(override: str = "") -> str | None:
    return _find_ffmpeg(override, package_file=__file__)


# ------------------------------------------------------------------ video
def _video_cmd(ffmpeg: str, list_file: str, out_mp4: str) -> list[str]:
    """Comando FFmpeg (concat de JPEGs con duraciones reales -> MP4). Puro."""
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-fps_mode", "vfr", out_mp4]


def _concat_list(frames: list[Frame], fps: int, tope_hueco: float = 10.0) -> str:
    """Lista del demuxer concat con la DURACION REAL de cada fotograma (a partir
    de sus timestamps). Sin esto, un buffer con huecos (sesion bloqueada, fallos
    de captura) produce un video con la linea de tiempo colapsada. Un hueco
    enorme se recorta a `tope_hueco` para no congelar la imagen minutos. Puro."""
    base = max(0.2, 1.0 / max(1, fps))
    lineas = []
    for i, f in enumerate(frames):
        if i + 1 < len(frames):
            dur = min(max(frames[i + 1].ts - f.ts, 0.05), tope_hueco)
        else:
            dur = base
        lineas.append(f"file 'f_{i:05d}.jpg'\nduration {dur:.3f}\n")
    if frames:
        # peculiaridad del demuxer concat: la ultima duracion solo se respeta
        # si el ultimo fichero aparece repetido al final
        lineas.append(f"file 'f_{len(frames) - 1:05d}.jpg'\n")
    return "".join(lineas)


def build_video(ffmpeg: str, frames: list[Frame], out_mp4: str, fps: int = 1) -> str:
    """Vuelca los fotogramas del buffer a un MP4. Escribe los JPEG en la carpeta
    de trabajo SOLO durante el montaje y los borra al terminar (el disco no
    conserva nada del buffer)."""
    if not frames:
        raise IncidentError("El buffer esta vacio: aun no hay nada que guardar.")
    if not ffmpeg:
        raise IncidentError("No se encontro FFmpeg.")
    _purge_old_workdirs()
    wd = work_dir() / f"inc_{os.getpid()}_{int(time.time())}"
    wd.mkdir(parents=True, exist_ok=True)
    try:
        for i, f in enumerate(frames):
            (wd / f"f_{i:05d}.jpg").write_bytes(f.jpeg)
        list_file = wd / "list.txt"
        # formato concat: rutas relativas al cwd del proceso ffmpeg (la propia wd)
        list_file.write_text(_concat_list(frames, fps), encoding="utf-8")
        cmd = _video_cmd(ffmpeg, list_file.name, str(Path(out_mp4).resolve()))
        try:
            r = subprocess.run(cmd, cwd=str(wd), capture_output=True, timeout=300,
                               **subprocess_kwargs())
        except (OSError, subprocess.SubprocessError) as exc:
            _unlink_quiet(out_mp4)
            raise IncidentError(f"No se pudo ejecutar FFmpeg: {exc}") from exc
        if r.returncode != 0 or not Path(out_mp4).is_file():
            err = r.stderr.decode("utf-8", "replace")[-300:]
            _unlink_quiet(out_mp4)          # no dejar un .mp4 parcial/corrupto
            raise IncidentError(f"FFmpeg no pudo montar el video: {err}")
        return out_mp4
    finally:
        for p in wd.glob("*"):
            try:
                p.unlink()
            except OSError as exc:
                logger.warning("No se pudo borrar temporal %s: %s", p, exc)
        try:
            wd.rmdir()
        except OSError:
            pass


def _unlink_quiet(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _purge_old_workdirs() -> None:
    """Barre carpetas inc_* de montajes anteriores que murieron a medias: sin
    esto, capturas de pantalla huerfanas quedarian en disco para siempre."""
    import shutil
    try:
        for d in work_dir().glob("inc_*"):
            if d.is_dir() and not d.name.startswith(f"inc_{os.getpid()}_"):
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def pick_key_frames(frames: list[Frame], n: int = 6) -> list[Frame]:
    """Selecciona n fotogramas repartidos (primero, ultimos e intermedios) para
    ilustrar el PDF. Puro y testeable."""
    if len(frames) <= n:
        return list(frames)
    paso = (len(frames) - 1) / (n - 1)
    idx = sorted({round(i * paso) for i in range(n)})
    return [frames[i] for i in idx]


# ------------------------------------------------------- contexto del sistema
def _powershell_exe() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    p = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(p) if p.is_file() else "powershell"


def _pwsh(cmd: str, timeout: float = 20.0) -> str:
    # Forzamos UTF-8 en la salida DENTRO del comando: PowerShell 5.1 emite en la
    # pagina de codigos OEM por defecto y los mensajes con acentos salian con
    # mojibake en todos los dossieres de Windows en espanol.
    cmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        p = subprocess.run([_powershell_exe(), "-NoProfile", "-NonInteractive", "-Command", cmd],
                           capture_output=True, timeout=timeout, creationflags=flags)
        return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("PowerShell fallo: %s", exc)
        return ""


def parse_events(raw: str, max_items: int = 20) -> list[dict]:
    """Parsea la salida de Get-WinEvent con separador ||. Puro y testeable."""
    eventos = []
    for ln in raw.splitlines():
        partes = ln.split("||")
        if len(partes) < 4:
            continue
        hora, nivel, fuente, msg = partes[0].strip(), partes[1].strip(), partes[2].strip(), \
            "||".join(partes[3:]).strip()
        if not hora:
            continue
        eventos.append({"hora": hora, "nivel": nivel, "fuente": fuente,
                        "mensaje": msg[:220]})
        if len(eventos) >= max_items:
            break
    return eventos


def recent_events(minutos: int = 30) -> list[dict]:
    """Errores/advertencias recientes del Visor de eventos (System+Application)."""
    m = max(5, min(120, int(minutos)))
    cmd = ("Get-WinEvent -FilterHashtable @{LogName=@('System','Application');"
           "Level=1,2,3;StartTime=(Get-Date).AddMinutes(-" + str(m) + ")} -MaxEvents 20 "
           "-ErrorAction SilentlyContinue | ForEach-Object { $_.TimeCreated.ToString('HH:mm:ss') "
           "+ '||' + $_.LevelDisplayName + '||' + $_.ProviderName + '||' "
           "+ ($_.Message -replace \"`r`n|`n\", ' ') }")
    return parse_events(_pwsh(cmd, timeout=25))


def process_list(max_items: int = 25) -> list[str]:
    """Procesos con mas memoria (nombre + MB), para el dossier."""
    raw = _pwsh("Get-Process | Sort-Object WorkingSet64 -Descending | "
                f"Select-Object -First {int(max_items)} | "
                "ForEach-Object { $_.ProcessName + '||' + "
                "[math]::Round($_.WorkingSet64/1MB) }")
    out = []
    for ln in raw.splitlines():
        if "||" in ln:
            nombre, _, mb = ln.strip().rpartition("||")
            out.append(f"{nombre} ({mb} MB)")
    return out


def system_info() -> dict:
    import platform
    import sys
    info = {"equipo": os.environ.get("COMPUTERNAME", "?"),
            "windows": platform.platform()}
    try:
        build = sys.getwindowsversion().build
        info["windows"] = f"Windows {'11' if build >= 22000 else '10'} (build {build})"
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes
        info["dias_sin_reiniciar"] = f"{ctypes.windll.kernel32.GetTickCount64() / 86_400_000:.1f}"
    except Exception:  # noqa: BLE001
        pass
    return info


# ------------------------------------------------------------- transcripcion
def find_whisper_model() -> str | None:
    """Modelo ggml de Whisper si alguna app de la suite ya lo descargo."""
    try:
        d = models_dir()
        modelos = sorted(d.glob("ggml-*.bin"), key=lambda p: p.stat().st_size)
        return str(modelos[0]) if modelos else None
    except OSError:
        return None


def transcribe_wav(ffmpeg: str, wav_path: str) -> str | None:
    """Transcribe la nota de voz con el filtro whisper de FFmpeg (si el build lo
    trae y hay un modelo descargado por otra app de la suite). Best-effort."""
    model = find_whisper_model()
    if not model or not ffmpeg or not has_whisper(ffmpeg):
        return None
    # el nombre del modelo se interpola en el filtergraph: solo caracteres
    # seguros (una coma o corchete romperia el filtro en silencio)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", Path(model).name):
        logger.warning("Nombre de modelo no seguro para filtergraph: %s", Path(model).name)
        return None
    model_dir = str(Path(model).parent)
    tmp = Path(model_dir) / f".cn_tx_{os.getpid()}.srt"
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    filt = (f"aresample=16000,whisper=model={Path(model).name}:language=auto"
            f":use_gpu=false:destination={tmp.name}:format=srt")
    try:
        r = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                            "-i", str(Path(wav_path).resolve()), "-af", filt,
                            "-f", "null", "-"],
                           cwd=model_dir, capture_output=True, timeout=300,
                           **subprocess_kwargs())
        if r.returncode != 0 or not tmp.is_file():
            return None
        srt = tmp.read_text(encoding="utf-8", errors="replace")
        return srt_to_text(srt) or None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def srt_to_text(srt: str) -> str:
    """SRT -> texto plano (quita indices, tiempos y lineas vacias). Puro."""
    lineas = []
    for ln in srt.splitlines():
        s = ln.strip()
        if not s or s.isdigit() or re.match(r"^\d{2}:\d{2}:\d{2}", s):
            continue
        lineas.append(s)
    return " ".join(lineas).strip()
