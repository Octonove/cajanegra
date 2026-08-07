"""Tests de logica pura de CajaNegra (anillo, seleccion de fotogramas, parseo
de eventos, SRT y dossier). Ejecutar:  python -m pytest tests/ -q"""

import io
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cajanegra import incident, report  # noqa: E402
from cajanegra.buffer import Frame, FrameRing  # noqa: E402


def _jpeg(w=64, h=36, color=(40, 60, 90)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


# ------------------------------------------------------------------ anillo
def test_ring_evicts_by_age():
    r = FrameRing(max_age_s=10)
    for t in (0, 4, 8, 12, 16):
        r.add(Frame(ts=float(t), jpeg=b"x"))
    # con max 10s desde el ultimo (16): sobreviven 8, 12, 16
    assert [f.ts for f in r.snapshot()] == [8.0, 12.0, 16.0]
    assert r.seconds == 8.0


def test_ring_set_max_age_recorta():
    r = FrameRing(max_age_s=100)
    for t in range(0, 60, 10):
        r.add(Frame(ts=float(t), jpeg=b"x"))
    r.set_max_age(15)
    assert [f.ts for f in r.snapshot()] == [40.0, 50.0]


def test_ring_snapshot_es_copia():
    r = FrameRing(max_age_s=100)
    r.add(Frame(ts=1.0, jpeg=b"x"))
    s = r.snapshot()
    r.add(Frame(ts=2.0, jpeg=b"y"))
    assert len(s) == 1 and r.count == 2


def test_ring_bytes_used():
    r = FrameRing(max_age_s=100)
    r.add(Frame(ts=1.0, jpeg=b"abc"))
    r.add(Frame(ts=2.0, jpeg=b"de"))
    assert r.bytes_used == 5


# ------------------------------------------------------- fotogramas clave
def test_pick_key_frames_pocos():
    fr = [Frame(ts=float(i), jpeg=b"x") for i in range(4)]
    assert incident.pick_key_frames(fr, n=6) == fr


def test_pick_key_frames_reparte():
    fr = [Frame(ts=float(i), jpeg=b"x") for i in range(100)]
    sel = incident.pick_key_frames(fr, n=6)
    assert len(sel) == 6
    assert sel[0].ts == 0.0 and sel[-1].ts == 99.0
    assert all(sel[i].ts < sel[i + 1].ts for i in range(len(sel) - 1))


# ------------------------------------------------------------- comando video
def test_video_cmd_construccion():
    cmd = incident._video_cmd("ffmpeg.exe", "list.txt", "out.mp4")
    assert cmd[0] == "ffmpeg.exe" and cmd[-1] == "out.mp4"
    assert "concat" in cmd and "libx264" in cmd
    assert "vfr" in cmd                    # respeta las duraciones del concat
    # dimensiones pares (yuv420p exige ancho/alto pares)
    assert any("trunc(iw/2)*2" in c for c in cmd)


def test_concat_list_duraciones_reales():
    fr = [Frame(ts=100.0, jpeg=b"x"), Frame(ts=101.0, jpeg=b"x"),
          Frame(ts=131.0, jpeg=b"x")]      # hueco de 30 s entre el 2o y el 3o
    txt = incident._concat_list(fr, fps=1)
    lineas = txt.splitlines()
    assert lineas[0] == "file 'f_00000.jpg'"
    assert lineas[1] == "duration 1.000"
    assert lineas[3] == "duration 10.000"      # el hueco de 30 s se recorta al tope
    # el ultimo fichero se repite (peculiaridad del demuxer concat)
    assert lineas[-1] == "file 'f_00002.jpg'"


def test_build_video_sin_frames_lanza():
    with pytest.raises(incident.IncidentError):
        incident.build_video("ffmpeg.exe", [], "out.mp4")


def test_ring_tope_de_bytes():
    r = FrameRing(max_age_s=9999, max_bytes=10)
    r.add(Frame(ts=1.0, jpeg=b"aaaa"))
    r.add(Frame(ts=2.0, jpeg=b"bbbb"))
    r.add(Frame(ts=3.0, jpeg=b"cccc"))     # 12 bytes > 10: expulsa el mas viejo
    assert r.count == 2 and r.bytes_used == 8
    assert r.snapshot()[0].ts == 2.0


# ------------------------------------------------------------------ eventos
def test_parse_events():
    raw = ("12:01:03||Error||Application Error||La aplicacion X fallo\n"
           "linea basura sin separador\n"
           "12:05:44||Advertencia||Kernel-Power||Mensaje con||separador interno\n")
    ev = incident.parse_events(raw)
    assert len(ev) == 2
    assert ev[0]["fuente"] == "Application Error"
    assert ev[1]["mensaje"].startswith("Mensaje con||separador")


def test_parse_events_limite():
    raw = "\n".join(f"12:00:0{i%10}||Error||F{i}||m" for i in range(30))
    assert len(incident.parse_events(raw, max_items=20)) == 20


# ---------------------------------------------------------------------- SRT
def test_srt_to_text():
    srt = "1\n00:00:00,000 --> 00:00:02,000\nHola mundo\n\n2\n00:00:02,000 --> 00:00:04,000\nsegunda linea\n"
    assert incident.srt_to_text(srt) == "Hola mundo segunda linea"


# -------------------------------------------------------------------- dossier
def test_dossier_pdf(tmp_path):
    import fitz
    frames = [Frame(ts=1000.0 + i, jpeg=_jpeg(color=(30 + i * 20, 60, 90))) for i in range(5)]
    out = str(tmp_path / "dossier.pdf")
    report.exportar_dossier(
        out, momento=datetime(2026, 7, 12, 17, 30, 5),
        testimonio="Estaba pegando datos en el <Excel> & se cerro solo.",
        transcripcion="se cerro sin avisar",
        frames_clave=frames,
        eventos=[{"hora": "17:29:58", "nivel": "Error", "fuente": "Application Error",
                  "mensaje": "EXCEL.EXE fallo con codigo <0xc0000005>"}],
        procesos=["chrome (900 MB)", "EXCEL (450 MB)"],
        sysinfo={"equipo": "PC-TIENDA", "windows": "Windows 11 (build 26200)"},
        video_path="incidente.mp4", segundos_buffer=180.0)
    doc = fitz.open(out)
    text = "\n".join(doc[p].get_text("text") for p in range(doc.page_count))
    n_imgs = sum(len(doc[p].get_images()) for p in range(doc.page_count))
    doc.close()
    assert "Informe de incidente" in text
    assert "PC-TIENDA" in text and "Application Error" in text
    assert "<Excel>" in text            # escapado como texto, no interpretado
    assert n_imgs == 5                  # los 5 fotogramas clave embebidos


def test_partir_texto_multilinea_reconstruye_exacto():
    texto = "\n".join(f"Linea {i} con algo de texto" for i in range(100))
    bloques = report.partir_texto(texto)
    assert len(bloques) > 1
    assert "\n".join(bloques) == texto
    assert all(len(b.split("\n")) <= 30 for b in bloques)


def test_partir_texto_linea_gigante_sin_espacios():
    # una sola linea de 4000 chars sin espacios: se corta en seco sin perder nada
    texto = "A" * 4000
    bloques = report.partir_texto(texto)
    assert len(bloques) > 1
    assert "".join(bloques) == texto
    assert all(len(b) <= 1500 for b in bloques)


def test_quebrar_rachas():
    # racha larga sin espacios: gana puntos de corte U+200B cada 40 chars
    out = report.quebrar_rachas("X" * 100)
    assert out.replace("\u200b", "") == "X" * 100
    assert out.count("\u200b") == 2
    # el texto normal (palabras cortas) queda intacto
    assert report.quebrar_rachas("hola mundo normal") == "hola mundo normal"


def test_dossier_pdf_testimonio_largo_no_trunca_ni_encoge(tmp_path):
    """Regresion: un testimonio mas largo que una pagina se emitia en un solo
    insert_htmlbox, que encogia la fuente hasta 5pt y truncaba el final en
    silencio. Ahora se pagina por bloques."""
    import fitz
    out = str(tmp_path / "largo.pdf")
    testimonio = "\n".join(f"Linea {i} del testimonio con algo de texto para que ocupe"
                           for i in range(1, 121))
    report.exportar_dossier(
        out, momento=datetime(2026, 7, 12, 17, 30), testimonio=testimonio,
        transcripcion=None, frames_clave=[], eventos=[], procesos=[],
        sysinfo={}, video_path=None, segundos_buffer=60.0)
    doc = fitz.open(out)
    text = "\n".join(doc[p].get_text("text") for p in range(doc.page_count))
    sizes = {round(s["size"], 1)
             for p in range(doc.page_count)
             for b in doc[p].get_text("dict")["blocks"]
             for l in b.get("lines", [])
             for s in l["spans"]}
    n_pages = doc.page_count
    doc.close()
    text = text.replace("\u200b", "")
    assert n_pages > 1                      # el testimonio pagina, no se aplasta
    assert "Linea 1 " in text and "Linea 60 " in text and "Linea 120" in text
    assert min(sizes) >= 8.0                # nada encogido por debajo del pie (8px)


def test_dossier_pdf_sin_datos_opcionales(tmp_path):
    import fitz
    out = str(tmp_path / "min.pdf")
    report.exportar_dossier(
        out, momento=datetime(2026, 7, 12, 17, 30), testimonio="",
        transcripcion=None, frames_clave=[], eventos=[], procesos=[],
        sysinfo={}, video_path=None, segundos_buffer=0.0)
    doc = fitz.open(out)
    text = doc[0].get_text("text")
    doc.close()
    assert "sin descripcion" in text
    assert "Sin errores recientes" in text


def test_pid_de_workdir():
    from cajanegra.incident import _pid_de_workdir
    assert _pid_de_workdir("inc_1234_1700000000") == 1234
    assert _pid_de_workdir("inc_abc_1700000000") is None
    assert _pid_de_workdir("otracosa") is None


def test_debe_purgarse():
    import os
    from cajanegra.incident import debe_purgarse
    # carpeta vieja: se purga siempre, viva o no
    assert debe_purgarse(os.getpid(), 25.0) is True
    # pid VIVO (el nuestro) y carpeta reciente: NO se purga
    assert debe_purgarse(os.getpid(), 1.0) is False
    # pid inexistente y reciente: se purga (proceso muerto)
    assert debe_purgarse(999999999, 1.0) is True
    # nombre raro (pid None) reciente: no tocar hasta que envejezca
    assert debe_purgarse(None, 1.0) is False


def test_instancia_unica_mutex():
    """El guard detecta un mutex ya adquirido desde OTRO proceso."""
    import subprocess
    import sys
    sys.path.insert(0, ".")
    from CajaNegra import _single_instance
    nombre = f"Local\CajaNegraTest{__import__('os').getpid()}"
    assert _single_instance(nombre) is True          # 1a adquisicion: libre
    code = (
        "import sys; sys.path.insert(0, r'" + __import__("os").getcwd() + "');"
        "from CajaNegra import _single_instance;"
        f"sys.exit(0 if not _single_instance(r'{nombre}') else 1)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
