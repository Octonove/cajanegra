"""Dossier PDF del incidente (PyMuPDF), estilo informe de accidente: que paso,
cuando, testimonio, fotogramas clave, errores del sistema y procesos activos.

El texto se dibuja con insert_htmlbox midiendo el alto real (leccion de la
suite: insert_textbox con altos manuales descarta texto en silencio)."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .buffer import Frame

PW, PH, M = 595, 842, 42
TW = PW - 2 * M
NAVY = "#1e3a5f"
ROJO = "#b91c1c"


class ReportError(Exception):
    pass


def _measure(html_str: str, width: float) -> float:
    import fitz
    d = fitz.open()
    try:
        pg = d.new_page(width=width + 80, height=4000)
        spare, _ = pg.insert_htmlbox(fitz.Rect(0, 0, width, 4000), html_str)
        return max(1.0, 4000 - spare)
    finally:
        d.close()


def _rgb(hexcolor: str):
    c = hexcolor.lstrip("#")
    return int(c[0:2], 16) / 255, int(c[2:4], 16) / 255, int(c[4:6], 16) / 255


def exportar_dossier(out_path: str, *, momento: datetime, testimonio: str,
                     transcripcion: str | None, frames_clave: list[Frame],
                     eventos: list[dict], procesos: list[str], sysinfo: dict,
                     video_path: str | None, segundos_buffer: float) -> str:
    import fitz
    doc = fitz.open()
    try:
        page = doc.new_page(width=PW, height=PH)
        y = M

        def put(html_str: str, gap: float = 6.0):
            nonlocal y, page
            h = _measure(html_str, TW)
            if y + h > PH - M:
                page = doc.new_page(width=PW, height=PH)
                y = M
            page.insert_htmlbox(fitz.Rect(M, y, PW - M, min(y + h + 2, PH - M)), html_str)
            y += h + gap

        def titulo(txt: str):
            put(f'<div style="font-family:sans-serif;font-size:13px;font-weight:bold;'
                f'color:{NAVY};border-bottom:1px solid #e2e8f0;padding-bottom:2px">{txt}</div>', 5)

        # cabecera
        page.draw_rect(fitz.Rect(0, 0, PW, 86), color=_rgb(NAVY), fill=_rgb(NAVY))
        page.insert_htmlbox(fitz.Rect(M, 16, PW - M, 56),
                            '<div style="font-family:sans-serif;font-size:22px;font-weight:bold;'
                            'color:#ffffff">Informe de incidente</div>')
        page.insert_htmlbox(fitz.Rect(M, 52, PW - M, 82),
                            '<div style="font-family:sans-serif;font-size:10px;color:#b7c7da">'
                            'CajaNegra · generado 100% en el equipo del usuario</div>')
        y = 100

        put(f'<div style="font-family:sans-serif;font-size:11px;color:#334155">'
            f'<b>Fecha y hora:</b> {momento.strftime("%d/%m/%Y %H:%M:%S")} &nbsp;·&nbsp; '
            f'<b>Equipo:</b> {html.escape(sysinfo.get("equipo", "?"))} &nbsp;·&nbsp; '
            f'<b>Sistema:</b> {html.escape(sysinfo.get("windows", "?"))}<br>'
            f'<b>Video adjunto:</b> {html.escape(Path(video_path).name) if video_path else "no"} '
            f'&nbsp;·&nbsp; <b>Buffer congelado:</b> ultimos {segundos_buffer:.0f} s de pantalla'
            + (f' &nbsp;·&nbsp; <b>Dias sin reiniciar:</b> {html.escape(str(sysinfo.get("dias_sin_reiniciar")))}'
               if sysinfo.get("dias_sin_reiniciar") else "") + '</div>', 10)

        # testimonio
        titulo("Que estaba pasando (testimonio del usuario)")
        cuerpo = html.escape(testimonio.strip() or "(sin descripcion)").replace("\n", "<br>")
        put(f'<div style="font-family:sans-serif;font-size:10px;color:#334155;line-height:1.5">'
            f'{cuerpo}</div>', 8)
        if transcripcion:
            put(f'<div style="font-family:sans-serif;font-size:10px;color:#64748b;'
                f'line-height:1.5"><b>Nota de voz (transcrita en local):</b> '
                f'{html.escape(transcripcion)}</div>', 8)

        # fotogramas clave
        if frames_clave:
            titulo("Fotogramas clave (del mas antiguo al mas reciente)")
            img_w = (TW - 12) / 2
            col = 0
            last_h = 0.0
            for f in frames_clave:
                try:
                    pix = fitz.Pixmap(f.jpeg)
                    ratio = img_w / pix.width
                    img_h = pix.height * ratio
                except Exception:  # noqa: BLE001
                    continue
                if y + img_h + 16 > PH - M:
                    page = doc.new_page(width=PW, height=PH)
                    y = M
                    col = 0
                x0 = M + col * (img_w + 12)
                page.insert_image(fitz.Rect(x0, y, x0 + img_w, y + img_h), stream=f.jpeg)
                page.insert_htmlbox(
                    fitz.Rect(x0, y + img_h + 1, x0 + img_w, y + img_h + 14),
                    f'<div style="font-family:sans-serif;font-size:7px;color:#94a3b8">'
                    f'{datetime.fromtimestamp(f.ts).strftime("%H:%M:%S")}</div>')
                last_h = img_h
                col += 1
                if col == 2:
                    col = 0
                    y += img_h + 20
            if col == 1:       # fila impar: avanzar con la altura YA calculada
                y += last_h + 20
            y += 4

        # eventos del sistema
        titulo("Errores y advertencias recientes de Windows")
        if eventos:
            filas = "".join(
                f'<tr><td style="padding:2px 6px;white-space:nowrap;color:#64748b">{html.escape(e["hora"])}</td>'
                f'<td style="padding:2px 6px;white-space:nowrap;color:{ROJO}">{html.escape(e["nivel"])}</td>'
                f'<td style="padding:2px 6px"><b>{html.escape(e["fuente"])}</b> — '
                f'{html.escape(e["mensaje"])}</td></tr>' for e in eventos)
            put(f'<table style="font-family:sans-serif;font-size:8px;border-collapse:collapse">{filas}</table>', 8)
        else:
            put('<div style="font-family:sans-serif;font-size:10px;color:#64748b">'
                'Sin errores recientes en el Visor de eventos (o no se pudo consultar).</div>', 8)

        # procesos
        titulo("Procesos con mas memoria en el momento del reporte")
        if procesos:
            put('<div style="font-family:sans-serif;font-size:9px;color:#334155;line-height:1.5">'
                + html.escape(" · ".join(procesos)) + '</div>', 8)
        else:
            put('<div style="font-family:sans-serif;font-size:10px;color:#64748b">'
                'No se pudo obtener la lista de procesos.</div>', 8)

        # pie
        pie = ('<div style="font-family:sans-serif;font-size:8px;color:#94a3b8">'
               'Generado con CajaNegra (gratis y open source) · simplificaconia.com · '
               'El buffer vive solo en la memoria del equipo y no se guarda nada hasta que '
               'el usuario reporta.</div>')
        ph = _measure(pie, TW)
        if y + ph > PH - 20:
            page = doc.new_page(width=PW, height=PH)
        page.insert_htmlbox(fitz.Rect(M, PH - 20 - ph, PW - M, PH - 16), pie)

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        doc.save(out_path, garbage=3, deflate=True)
    finally:
        doc.close()
    return out_path
