"""Build the integration's brand images (icon/logo, light + dark) from the box photo in the KPN web UI.

Run from the repo root: python tools/make_brand.py [path/to/F5359s.png]
The photo isn't in the repo: save it from the box's web UI (an image named F5359s.png) to router/img/.
"""

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "router" / "img" / "F5359s.png"
OUT = ROOT / "custom_components" / "kpn_box" / "brand"
# Segoe UI Bold was used for the shipped images; DejaVu Sans Bold is the fallback on Linux
FONTS = (Path("C:/Windows/Fonts/segoeuib.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
FONT = next((f for f in FONTS if f.is_file()), FONTS[-1])
TEXT = "KPN Box"


def cropped(img: Image.Image) -> Image.Image:
    """Crop to the box; the photo has stray specks that an erode pass removes from the bounding box."""
    alpha = img.getchannel("A").point(lambda a: 255 if a > 24 else 0)
    left, top, right, bottom = alpha.filter(ImageFilter.MinFilter(9)).getbbox()
    pad = 6  # give back what the erode took off the edges
    box = (max(left - pad, 0), max(top - pad, 0), min(right + pad, img.width), min(bottom + pad, img.height))
    return img.crop(box)


def outlined(img: Image.Image, width: int, color=(220, 220, 220, 255)) -> Image.Image:
    """Light halo behind the black box so it stays visible on dark backgrounds."""
    pad = width * 2
    canvas = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad))
    canvas.paste(img, (pad, pad), img)
    halo_mask = canvas.getchannel("A").filter(ImageFilter.MaxFilter(width * 2 + 1))
    halo = Image.new("RGBA", canvas.size, color)
    halo.putalpha(halo_mask)
    return Image.alpha_composite(halo, canvas)


def square(img: Image.Image, size: int, margin: float = 0.06) -> Image.Image:
    inner = round(size * (1 - 2 * margin))
    scale = inner / max(img.size)
    fitted = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size))
    canvas.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2), fitted)
    return canvas


def logo(img: Image.Image, height: int, text_color) -> Image.Image:
    box = square(img, height, margin=0.04)
    font = ImageFont.truetype(str(FONT), round(height * 0.42))
    left, top, right, bottom = font.getbbox(TEXT)
    gap = round(height * 0.12)
    canvas = Image.new("RGBA", (height + gap + (right - left) + round(height * 0.06), height))
    canvas.paste(box, (0, 0), box)
    ImageDraw.Draw(canvas).text(
        (height + gap - left, (height - (bottom - top)) // 2 - top), TEXT, font=font, fill=text_color
    )
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    photo = cropped(Image.open(SRC).convert("RGBA"))
    dark_photo = outlined(photo, width=max(4, photo.width // 120))
    for scale, suffix in ((1, ""), (2, "@2x")):
        square(photo, 256 * scale).save(OUT / f"icon{suffix}.png", optimize=True)
        square(dark_photo, 256 * scale).save(OUT / f"dark_icon{suffix}.png", optimize=True)
        logo(photo, 256 * scale, (0, 0, 0, 255)).save(OUT / f"logo{suffix}.png", optimize=True)
        logo(dark_photo, 256 * scale, (255, 255, 255, 255)).save(OUT / f"dark_logo{suffix}.png", optimize=True)
    for f in sorted(OUT.glob("*.png")):
        print(f.name, Image.open(f).size)


if __name__ == "__main__":
    main()
