"""Fotos für die öffentliche Darstellung: verkleinern, drehen laut Kamera, Metadaten (EXIF, GPS) entfernen,
kleines Vorschaubild erzeugen. Hochgeladene Originale werden nicht aufbewahrt."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600          # längere Kante der Anzeige-Fassung
THUMB_SIDE = 480         # längere Kante der Vorschau (Kacheln, Listen, Karte)
MAX_PIXELS = 50_000_000  # größere Bilder (z. B. Panoramen mit 50 MP) werden abgelehnt – Schutz vor „Pixelbomben“
QUALITY = 84


def _flatten(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB")


def _jpeg(img: Image.Image, side: int) -> bytes:
    img = img.copy()
    img.thumbnail((side, side), Image.LANCZOS)
    out = io.BytesIO()
    # ohne exif=…: es werden keine Metadaten (Kamera, Zeitpunkt, GPS) übernommen
    img.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def process(content: bytes) -> tuple[bytes, bytes, tuple[int, int]]:
    """Gibt (Anzeige-JPEG, Vorschau-JPEG, (Breite, Höhe)) zurück. ValueError bei unlesbaren/zu großen Bildern."""
    try:
        with Image.open(io.BytesIO(content)) as probe:
            if probe.format not in ("JPEG", "PNG", "WEBP", "MPO"):
                raise ValueError("Nur JPG, PNG oder WebP.")
            if probe.width * probe.height > MAX_PIXELS:
                raise ValueError("Das Bild ist zu groß (mehr als 50 Megapixel).")
            probe.draft("RGB", (MAX_SIDE, MAX_SIDE))   # JPEG gleich verkleinert dekodieren (schnell, wenig Speicher)
            img = ImageOps.exif_transpose(probe)       # Hochkant-Fotos richtig herum
            img = _flatten(img)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Die Datei ist kein lesbares Bild.") from exc
    full = _jpeg(img, MAX_SIDE)
    thumb = _jpeg(img, THUMB_SIDE)
    w, h = img.size
    scale = min(1.0, MAX_SIDE / max(w, h))
    return full, thumb, (round(w * scale), round(h * scale))


def thumbnail(content: bytes) -> bytes:
    """Vorschau zu einem bereits gespeicherten Foto (für Fotos aus älteren Versionen)."""
    with Image.open(io.BytesIO(content)) as img:
        img.draft("RGB", (THUMB_SIDE * 2, THUMB_SIDE * 2))
        return _jpeg(_flatten(ImageOps.exif_transpose(img)), THUMB_SIDE)
