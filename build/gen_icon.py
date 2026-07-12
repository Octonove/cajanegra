"""Genera build/icon.ico para CajaNegra (anillo de buffer + bandera de reporte)."""

from pathlib import Path
from PIL import Image, ImageDraw

NAVY = (30, 58, 95, 255)
NAVY2 = (21, 48, 77, 255)
TERRA = (206, 110, 97, 255)
RED = (239, 68, 68, 255)
WHITE = (255, 255, 255, 255)


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=NAVY)
    d.rounded_rectangle([0, int(size * 0.5), size - 1, size - 1], radius=r, fill=NAVY2)
    # anillo del buffer circular (arco abierto, como "grabando en bucle")
    cx, cy = int(size * 0.5), int(size * 0.54)
    rad = int(size * 0.28)
    w = max(3, size // 14)
    d.arc([cx - rad, cy - rad, cx + rad, cy + rad], start=300, end=210,
          fill=TERRA, width=w)
    # punta de flecha del bucle
    ax, ay = int(cx + rad * 0.52), int(cy - rad * 0.86)
    s = max(3, size // 12)
    d.polygon([(ax, ay), (ax + s, ay + s // 2), (ax, ay + s)], fill=TERRA)
    # bandera de "reportar incidente" en el centro
    fx, fy = int(cx - size * 0.06), int(cy - size * 0.16)
    d.line([fx, fy, fx, fy + int(size * 0.30)], fill=WHITE, width=max(2, size // 22))
    d.polygon([(fx, fy), (fx + int(size * 0.18), fy + int(size * 0.07)),
               (fx, fy + int(size * 0.14))], fill=RED)
    return img


def main() -> None:
    out = Path(__file__).resolve().parent / "icon.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [make(s) for s in sizes]
    imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes])
    make(256).save(out.with_name("icon_preview.png"))
    print("icono ->", out)


if __name__ == "__main__":
    main()
