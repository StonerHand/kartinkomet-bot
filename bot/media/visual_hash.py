from io import BytesIO

from PIL import Image


def image_dhash(image_bytes: bytes) -> str | None:
    """64-bit difference hash as 16 hex chars, or None if the bytes aren't a readable image."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            grayscale = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = list(grayscale.getdata())
    except (OSError, Image.DecompressionBombError, ValueError):
        return None

    value = 0
    for row in range(8):
        row_offset = row * 9
        for column in range(8):
            value <<= 1
            if pixels[row_offset + column] > pixels[row_offset + column + 1]:
                value |= 1

    return f"{value:016x}"
