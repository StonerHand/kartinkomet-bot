from __future__ import annotations

from io import BytesIO


def image_dhash(image_bytes: bytes) -> str | None:
    pillow = _pillow_image()
    if pillow is None:
        return None

    Image = pillow
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            grayscale = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = list(grayscale.getdata())
    except OSError:
        return None

    value = 0
    for row in range(8):
        row_offset = row * 9
        for column in range(8):
            value <<= 1
            if pixels[row_offset + column] > pixels[row_offset + column + 1]:
                value |= 1

    return f"{value:016x}"


def visual_hash_distance(left: str | None, right: str | None) -> int | None:
    if not left or not right:
        return None

    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return None


def _pillow_image():
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return None

    return Image
