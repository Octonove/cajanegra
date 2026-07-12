"""Ventana principal de CajaNegra: vigilancia con buffer en RAM, boton (y atajo
global Ctrl+Alt+F9) de 'Reportar incidente' y generacion del dossier."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import APP_NAME, APP_VERSION, theme
from . import buffer as buf
from . import incident, report, voice
from .config import AppConfig, load_config, save_config, work_dir

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_CONTROL, MOD_ALT = 0x0002, 0x0001
VK_F9 = 0x78
HOTKEY_TXT = "Ctrl+Alt+F9"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("720x560")
        self.minsize(680, 520)
        theme.apply(self)
        try:
            ico = Path(__file__).resolve().parent.parent / "build" / "icon.ico"
            if ico.is_file():
                self.iconbitmap(str(ico))
        except tk.TclError:
            pass

        self.cfg: AppConfig = load_config()
        self.box = buf.BlackBox(minutos=self.cfg.minutos, fps=self.cfg.fps)
        self.ffmpeg = incident.find_ffmpeg(self.cfg.ffmpeg_path) or ""
        self._closing = False
        self._reporting = False
        self._hk_thread_id: int | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_hotkey()
        self.after(300, self._first_run_check)
        self.after(700, self._tick)
        if self.cfg.autostart:
            self._toggle_watch()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        theme.header(self, APP_NAME, "La caja negra de tu PC · el pasado reciente, siempre disponible")
        self.status = theme.status_bar(self, "Parada. Pulsa 'Vigilar' para llenar el buffer.")

        top = ttk.Frame(self, padding=(16, 12))
        top.pack(fill="x")
        self.btn_watch = ttk.Button(top, text="●  Vigilar", style="Rec.TButton",
                                    command=self._toggle_watch)
        self.btn_watch.pack(side="left")
        self.lbl_estado = ttk.Label(top, text="", style="Big.TLabel")
        self.lbl_estado.pack(side="left", padx=(16, 0))
        ttk.Button(top, text="Carpeta de salida…", command=self._set_output_dir).pack(side="right")

        # tarjeta de privacidad (siempre visible: transparencia radical)
        priv = ttk.LabelFrame(self, text="Privacidad", padding=10)
        priv.pack(fill="x", padx=16, pady=(4, 0))
        ttk.Label(priv, style="CardMuted.TLabel", justify="left", text=(
            "• El buffer vive SOLO en la memoria RAM: no se escribe nada en disco hasta que "
            "TU reportas.\n"
            "• No hay audio continuo: la unica grabacion posible es tu nota de voz voluntaria "
            "de 30 s al reportar.\n"
            "• Al pausar o cerrar la app, el buffer se descarta. Nada sale de tu equipo.")).pack(anchor="w")

        # ajustes
        opts = ttk.Frame(self, padding=(16, 10))
        opts.pack(fill="x")
        ttk.Label(opts, text="Minutos de memoria:", style="Muted.TLabel").pack(side="left")
        self.var_min = tk.IntVar(value=self.cfg.minutos)
        sp = ttk.Spinbox(opts, from_=1, to=10, textvariable=self.var_min, width=4,
                         command=self._on_minutos)
        sp.pack(side="left", padx=(6, 18))
        # los valores TECLEADOS tambien deben aplicarse (no solo las flechas)
        sp.bind("<Return>", lambda _e: self._on_minutos())
        sp.bind("<FocusOut>", lambda _e: self._on_minutos())
        ttk.Label(opts, text="Capturas/seg:", style="Muted.TLabel").pack(side="left")
        self.var_fps = tk.IntVar(value=self.cfg.fps)
        spf = ttk.Spinbox(opts, from_=1, to=2, textvariable=self.var_fps, width=4,
                          command=self._on_fps)
        spf.pack(side="left", padx=(6, 18))
        spf.bind("<Return>", lambda _e: self._on_fps())
        spf.bind("<FocusOut>", lambda _e: self._on_fps())
        self.var_auto = tk.BooleanVar(value=self.cfg.autostart)
        ttk.Checkbutton(opts, text="Vigilar al abrir la app", variable=self.var_auto,
                        command=self._on_autostart).pack(side="left")

        # boton grande de reporte
        big = ttk.Frame(self, padding=(16, 14))
        big.pack(fill="both", expand=True)
        self.btn_report = ttk.Button(big, text=f"⚑  REPORTAR INCIDENTE   ({HOTKEY_TXT})",
                                     style="Primary.TButton", command=self._report)
        self.btn_report.pack(fill="x", ipady=16)
        ttk.Label(big, style="Muted.TLabel", justify="left", text=(
            "¿Acaba de pasar algo raro (un error, un cuelgue, algo que no sabes repetir)?\n"
            "Pulsa el boton — tambien funciona el atajo aunque esta ventana este minimizada —\n"
            "y CajaNegra congelara los ultimos minutos y montara el dossier para tu informatico."
        )).pack(anchor="w", pady=(10, 0))

    # ------------------------------------------------------------ vigilancia
    def _toggle_watch(self) -> None:
        if self.box.running:
            self.box.stop()
            self.box.clear()          # privacidad: al pausar, el buffer se descarta
            self.btn_watch.config(text="●  Vigilar")
            self._set_status("Parada. El buffer se ha descartado.")
        else:
            self.box.start()
            self.btn_watch.config(text="⏹  Pausar")
            self._set_status("Vigilando…")

    def _tick(self) -> None:
        if self._closing:
            return
        n, seg, mb = self.box.stats()
        if self.box.running:
            if self.box.error:
                self.lbl_estado.config(text="⚠ VIGILANDO con problemas de captura",
                                       foreground="#D97706")
                self._set_status(self.box.error)
            else:
                self.lbl_estado.config(
                    text=f"● VIGILANDO · {seg:.0f}s en memoria ({n} fotogramas, {mb:.0f} MB)",
                    foreground=theme.REC)
        else:
            # el hilo pudo morir al arrancar (sin mss, sin permisos…): reflejarlo
            if self.box.error:
                self.lbl_estado.config(text="⚠ Captura no disponible", foreground=theme.DANGER)
                self._set_status(self.box.error)
                self.btn_watch.config(text="●  Vigilar")
            else:
                self.lbl_estado.config(text="○ En pausa", foreground=theme.MUTED)
        self.after(700, self._tick)

    def _on_minutos(self) -> None:
        try:
            v = int(self.var_min.get())
        except tk.TclError:
            return
        self.cfg.minutos = max(1, min(10, v))
        if self.cfg.minutos != v:
            self.var_min.set(self.cfg.minutos)    # refleja el clamp en la UI
        self.box.set_minutos(self.cfg.minutos)
        save_config(self.cfg)

    def _on_fps(self) -> None:
        try:
            v = int(self.var_fps.get())
        except tk.TclError:
            return
        self.cfg.fps = max(1, min(2, v))
        if self.cfg.fps != v:
            self.var_fps.set(self.cfg.fps)
        save_config(self.cfg)
        self.box.set_fps(self.cfg.fps)    # aplica en vivo SIN descartar el buffer

    def _on_autostart(self) -> None:
        self.cfg.autostart = bool(self.var_auto.get())
        save_config(self.cfg)

    # ------------------------------------------------------------ hotkey global
    def _start_hotkey(self) -> None:
        import ctypes.wintypes  # noqa: F401  (registra el submodulo)

        def runner():
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT, VK_F9):
                logger.warning("No se pudo registrar el atajo global %s.", HOTKEY_TXT)
                try:
                    self.after(0, lambda: self._set_status(
                        f"Atajo {HOTKEY_TXT} no disponible (lo usa otra aplicacion); "
                        "usa el boton de la ventana."))
                except (RuntimeError, tk.TclError):
                    pass
                return
            # solo con el registro OK: si fallara, un WM_QUIT posterior iria a
            # parar a un thread id reciclado por el sistema
            self._hk_thread_id = kernel32.GetCurrentThreadId()
            try:
                msg = ctypes.wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == WM_HOTKEY and not self._closing:
                        try:
                            self.after(0, self._report)
                        except (RuntimeError, tk.TclError):
                            break
            finally:
                user32.UnregisterHotKey(None, 1)
                self._hk_thread_id = None
        threading.Thread(target=runner, daemon=True).start()

    # -------------------------------------------------------------- reporte
    def _report(self) -> None:
        if self._reporting:
            return
        self._reporting = True          # tambien cubre el showinfo: sin esto, el
        try:                            # hotkey repetido apilaba avisos infinitos
            frames = self.box.snapshot()
            if not frames:
                self.deiconify()
                self.lift()
                messagebox.showinfo(APP_NAME, "El buffer esta vacio: activa 'Vigilar' y "
                                    "deja pasar unos segundos antes de reportar.",
                                    parent=self)
                self._reporting = False
                return
            self.deiconify()
            self.lift()
            ReportDialog(self, frames)
        except Exception:
            self._reporting = False
            raise

    def _report_done(self) -> None:
        self._reporting = False

    # -------------------------------------------------------------- varios
    def _set_output_dir(self) -> None:
        d = filedialog.askdirectory(title="Carpeta donde guardar los incidentes",
                                    initialdir=self.cfg.output_dir, parent=self)
        if d:
            self.cfg.output_dir = d
            save_config(self.cfg)
            self._set_status(f"Carpeta de salida: {d}")

    def _set_status(self, text: str) -> None:
        try:
            self.status.config(text=text)
        except tk.TclError:
            pass

    def _first_run_check(self) -> None:
        if self._closing or self.cfg.seen_welcome:
            return
        self.cfg.seen_welcome = True
        save_config(self.cfg)
        messagebox.showinfo(
            APP_NAME, "Bienvenido a CajaNegra.\n\n"
            "1. Deja la app vigilando (guarda en RAM los ultimos minutos de pantalla).\n"
            f"2. Cuando algo falle, pulsa 'Reportar incidente' (o {HOTKEY_TXT}).\n"
            "3. Cuenta que paso (texto o nota de voz) y CajaNegra genera un video + "
            "dossier PDF con los errores de Windows para enviar a tu informatico.\n\n"
            "Privacidad: nada toca el disco hasta que TU reportas, no hay audio continuo "
            "y nada sale de tu equipo.")

    def _on_close(self) -> None:
        self._closing = True
        try:
            if self._hk_thread_id:
                ctypes.windll.user32.PostThreadMessageW(self._hk_thread_id, 0x0012, 0, 0)  # WM_QUIT
        except (AttributeError, OSError):
            pass
        self.box.stop()
        self.destroy()


class ReportDialog(tk.Toplevel):
    """Que ha pasado + nota de voz opcional -> genera MP4 + PDF."""

    def __init__(self, app: App, frames):
        super().__init__(app)
        self.app = app
        self.frames = frames
        theme.center_window(self)
        self.title("Reportar incidente")
        self.configure(bg=theme.BG)
        self.transient(app)
        self.resizable(False, False)
        self.recorder: voice.VoiceRecorder | None = None
        self.wav_path = str(work_dir() / f"nota_{int(time.time())}.wav")
        self._building = False

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="¿Que estaba pasando?", style="H.TLabel").pack(anchor="w")
        ttk.Label(frm, text="Cuentalo con tus palabras (se incluye en el dossier).",
                  style="Muted.TLabel").pack(anchor="w")
        self.txt = tk.Text(frm, width=64, height=6, wrap="word", font=(theme.FONT, 10),
                           bg=theme.WHITE, relief="solid", borderwidth=1)
        self.txt.pack(fill="x", pady=(6, 8))
        row = ttk.Frame(frm)
        row.pack(fill="x")
        self.btn_voz = ttk.Button(row, text="🎙 Grabar nota de voz (max 30 s)",
                                  command=self._toggle_voz,
                                  state=("normal" if voice.AVAILABLE else "disabled"))
        self.btn_voz.pack(side="left")
        self.lbl_voz = ttk.Label(row, text="", style="Muted.TLabel")
        self.lbl_voz.pack(side="left", padx=(10, 0))

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(14, 0))
        self.btn_ok = ttk.Button(btns, text="Generar dossier", style="Primary.TButton",
                                 command=self._build)
        self.btn_ok.pack(side="right")
        ttk.Button(btns, text="Cancelar", command=self._cancel).pack(side="right", padx=(0, 6))
        self.lbl_prog = ttk.Label(frm, text="", style="Muted.TLabel")
        self.lbl_prog.pack(anchor="w", pady=(8, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.txt.focus_set()

    def _toggle_voz(self) -> None:
        if self.recorder and self.recorder.running:
            self.recorder.stop()
            self._voz_parada()
            return
        self.recorder = voice.VoiceRecorder(self.wav_path)
        self.recorder.start()
        self.btn_voz.config(text="⏹ Detener nota de voz")
        self.lbl_voz.config(text="Grabando…")
        self._poll_voz()

    def _poll_voz(self) -> None:
        """Refleja en la UI el auto-stop a los 30 s (sin esto, el boton seguia en
        'Detener' y una pulsacion tardia machacaba la nota ya grabada)."""
        if self.recorder is None:
            return
        if self.recorder.running:
            try:
                self.after(500, self._poll_voz)
            except tk.TclError:
                pass
            return
        self._voz_parada()

    def _voz_parada(self) -> None:
        try:
            self.btn_voz.config(text="🎙 Grabar de nuevo (sustituye la nota)")
            self.lbl_voz.config(text="Nota grabada." if (self.recorder and self.recorder.ok)
                                else ((self.recorder and self.recorder.error) or "No se grabo."))
        except tk.TclError:
            pass

    def _cancel(self) -> None:
        if self._building:
            return
        if self.recorder and self.recorder.running:
            self.recorder.stop()
        self._cleanup_wav()
        self.app._report_done()
        self.destroy()

    def _cleanup_wav(self) -> None:
        try:
            Path(self.wav_path).unlink(missing_ok=True)
        except OSError:
            pass

    def _build(self) -> None:
        if self._building:
            return
        self._building = True
        if self.recorder and self.recorder.running:
            self.recorder.stop()
            self.lbl_voz.config(text="Nota grabada." if self.recorder.ok else "")
        testimonio = self.txt.get("1.0", "end").strip()
        tiene_voz = bool(self.recorder and self.recorder.ok)
        self.btn_ok.config(state="disabled")
        self.btn_voz.config(state="disabled")
        self.lbl_prog.config(text="Montando el video y el dossier… (no cierres esta ventana)")
        frames = self.frames
        cfg = self.app.cfg
        ffmpeg = self.app.ffmpeg
        momento = datetime.now()
        stamp = momento.strftime("%Y-%m-%d_%H-%M-%S")
        outdir = Path(cfg.output_dir) / f"Incidente_{stamp}"

        def runner():
            video_path = None
            transcripcion = None
            error = None
            try:
                outdir.mkdir(parents=True, exist_ok=True)
                if ffmpeg:
                    try:
                        video_path = incident.build_video(
                            ffmpeg, frames, str(outdir / "incidente.mp4"), fps=cfg.fps)
                    except incident.IncidentError as exc:
                        logger.warning("video fallo: %s", exc)
                if tiene_voz:
                    import shutil
                    try:
                        shutil.copyfile(self.wav_path, str(outdir / "nota_de_voz.wav"))
                    except OSError:
                        pass
                    if ffmpeg:
                        transcripcion = incident.transcribe_wav(ffmpeg, self.wav_path)
                eventos = incident.recent_events()
                procesos = incident.process_list()
                sysinfo = incident.system_info()
                seg = frames[-1].ts - frames[0].ts if len(frames) > 1 else 0.0
                report.exportar_dossier(
                    str(outdir / "informe_incidente.pdf"), momento=momento,
                    testimonio=testimonio, transcripcion=transcripcion,
                    frames_clave=incident.pick_key_frames(frames),
                    eventos=eventos, procesos=procesos, sysinfo=sysinfo,
                    video_path=video_path, segundos_buffer=seg)
            except Exception as exc:  # noqa: BLE001
                logger.exception("dossier fallo")
                error = str(exc)
            finally:
                self._cleanup_wav()
            try:
                self.after(0, self._done, str(outdir), error)
            except (RuntimeError, tk.TclError):
                pass
        threading.Thread(target=runner, daemon=True).start()

    def _done(self, outdir: str, error: str | None) -> None:
        self._building = False
        self.app._report_done()
        try:
            self.destroy()
        except tk.TclError:
            pass
        if error:
            messagebox.showerror(APP_NAME, f"No se pudo generar el dossier:\n{error}")
            return
        self.app._set_status(f"Incidente guardado en: {outdir}")
        if messagebox.askyesno(APP_NAME, f"Dossier generado en:\n{outdir}\n\n"
                               "¿Abrir la carpeta para enviarlo?"):
            try:
                os.startfile(outdir)
            except OSError:
                pass


def main() -> None:
    from .config import setup_logging
    setup_logging()
    App().mainloop()
