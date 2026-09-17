# CajaNegra

La **caja negra de tu PC**, 100% local: mantiene en memoria los últimos minutos de tu pantalla y, cuando algo falla, pulsas **⚑ Reportar incidente** (o `Ctrl+Alt+F9`) y genera un **dossier perfecto para tu informático**: vídeo de lo que pasó, tu explicación (escrita o con nota de voz), los errores recientes de Windows y los procesos activos.

Se acabó el *"no sé, me salió un error y se cerró"*. Como el dashcam de un coche: **graba siempre, decides después**.

<!-- invokard-coffee -->
**&#9749; Si esto te ahorra tiempo, inv&iacute;tame a un caf&eacute;.** [![Inv&iacute;tame a un caf&eacute; con PayPal](https://img.shields.io/badge/PayPal-Inv%C3%ADtame%20a%20un%20caf%C3%A9-00457C?logo=paypal&logoColor=white)](https://www.paypal.com/donate/?business=stradoxx%40gmail.com&no_recurring=0&currency_code=EUR&item_name=Support%20cajanegra)

**USDC** &middot; Solana `5n6Gfosk7SdwbvdtE9xiLWpcGPBBBGDZYRfAkWyCk86g` &middot; Ethereum (ERC-20) `0xe176866f9d7fdb498e0d4a983d3e34d84dcd6bfc`

## 🔒 Privacidad por diseño

- El buffer vive **solo en la memoria RAM**: no se escribe nada en disco hasta que TÚ reportas.
- **No hay audio continuo**: la única grabación posible es tu nota de voz voluntaria de 30 s al reportar.
- Al pausar o cerrar la app, el buffer se descarta. Nada sale de tu equipo, sin cuentas ni nube.

## ⬇️ Descargar (Windows 10/11)

### ➡️ [**Descargar CajaNegra (instalador .exe)**](https://github.com/Octonove/cajanegra/releases/latest/download/CajaNegra-Setup.exe)

Descarga **directa** del instalador, sin registro. También puedes ver la [última versión y notas](https://github.com/Octonove/cajanegra/releases/latest).

> Si Windows muestra *"Windows protegió tu PC"* (es normal en programas nuevos sin firma): pulsa **Más información → Ejecutar de todas formas**. Se instala sin permisos de administrador.

## Cómo funciona

1. Deja CajaNegra **vigilando** (1-2 capturas por segundo de tu pantalla, últimos 1-10 minutos en RAM).
2. Cuando algo raro pase, pulsa **⚑ Reportar incidente** o `Ctrl+Alt+F9` (funciona con la ventana minimizada).
3. Cuenta qué estaba pasando (texto o 🎙 nota de voz de 30 s) y CajaNegra genera una carpeta con:
   - `incidente.mp4` — el vídeo de los últimos minutos (necesita [FFmpeg](https://ffmpeg.org); `winget install Gyan.FFmpeg`),
   - `informe_incidente.pdf` — el dossier: cronología, fotogramas clave, tu testimonio (con transcripción local por Whisper si otra app de la suite ya descargó el modelo), errores del Visor de eventos y procesos con más memoria,
   - `nota_de_voz.wav` — si la grabaste.
4. Envía la carpeta por email o WhatsApp a tu informático. Fin de la adivinación.

## Stack

Python 3 + Tkinter (ttk) · mss + Pillow (buffer) · FFmpeg (vídeo, filtro whisper opcional) · soundcard (nota de voz) · PyMuPDF (dossier) · ctypes/Win32.

Depende del paquete compartido de la suite [`octonove-core`](https://github.com/Octonove/octonove-core) (tema, config, FFmpeg): debe estar en el `sys.path` del entorno (vía `.pth` o copia junto al proyecto).

## Compilar

```powershell
.\build\build.ps1              # ejecutable (PyInstaller onedir)
.\build\build-installer.ps1    # instalador (Inno Setup)
```

## Tests

```powershell
python -m pytest tests/ -q
```

## Licencia

[MIT](LICENSE) — © 2026 Octonove.
