# Avisos de terceros (Third-Party Notices)

CajaNegra empaqueta y/o utiliza los siguientes componentes de terceros:

## PyMuPDF (fitz) — GNU AGPL v3
CajaNegra incluye **PyMuPDF** (https://pymupdf.io) como biblioteca para la
generación del dossier PDF. PyMuPDF se distribuye bajo la **GNU Affero General
Public License v3 (AGPL-3.0)**, con opción de licencia comercial ofrecida por
Artifex Software.

- Proyecto: https://github.com/pymupdf/PyMuPDF
- Licencia comercial (Artifex): https://artifex.com/licensing
- Texto de la licencia AGPL: https://www.gnu.org/licenses/agpl-3.0.html

**Nota sobre la AGPL:** dado que CajaNegra empaqueta PyMuPDF (AGPL-3.0), el
código fuente completo de la aplicación está disponible en este mismo
repositorio, lo que satisface los requisitos de la AGPL para esta distribución.

## Otras dependencias
- **Pillow** (PIL) — licencia HPND/MIT-CMU — https://python-pillow.org
- **mss** — licencia MIT — https://github.com/BoboTiG/python-mss
- **soundcard** — licencia BSD-3-Clause — https://github.com/bastibe/SoundCard
- **numpy** — licencia BSD-3-Clause — https://numpy.org

## FFmpeg (no empaquetado)
CajaNegra **no incluye** FFmpeg: lo localiza si ya está instalado en el sistema
(p. ej. `winget install Gyan.FFmpeg`). FFmpeg se distribuye bajo LGPL/GPL según
la build — https://ffmpeg.org/legal.html

El resto del código de CajaNegra se distribuye bajo licencia MIT (ver `LICENSE`).
