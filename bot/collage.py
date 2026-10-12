"""Arena collage: fighters side by side (duel) or in a 2×2 grid (tournament), each with a
big coloured badge, so voters can see which pic is 🅰️/🅱️ or 1–4 in a single message."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

CELL = 640
GAP = 8
BACKGROUND = (24, 24, 28)
# Same colours as the vote bars: 🟥 🟦 🟩 🟨
BADGE_COLORS = ((229, 57, 53), (30, 136, 229), (67, 160, 71), (253, 216, 53))
BADGE_TEXT = ((255, 255, 255), (255, 255, 255), (255, 255, 255), (33, 33, 33))
DUEL_BADGES = ("A", "B")
TOURNAMENT_BADGES = ("1", "2", "3", "4")


def _cell(image_bytes: bytes) -> Image.Image:
    """The pic scaled to fit a CELL×CELL square (no cropping) on the dark background."""
    with Image.open(BytesIO(image_bytes)) as source:
        source.draft("RGB", (CELL, CELL))  # cheap JPEG downscale while decoding
        picture = source.convert("RGB")
    picture.thumbnail((CELL, CELL), Image.Resampling.LANCZOS)
    cell = Image.new("RGB", (CELL, CELL), BACKGROUND)
    cell.paste(picture, ((CELL - picture.width) // 2, (CELL - picture.height) // 2))
    return cell


def _badge(canvas: Image.Image, x: int, y: int, slot: int, label: str) -> None:
    draw = ImageDraw.Draw(canvas)
    size = 120
    left, top = x + 18, y + 18
    draw.ellipse(
        (left - 4, top - 4, left + size + 4, top + size + 4), fill=(255, 255, 255)
    )
    draw.ellipse((left, top, left + size, top + size), fill=BADGE_COLORS[slot])
    font = ImageFont.load_default(size=78)
    draw.text(
        (left + size / 2, top + size / 2),
        label,
        font=font,
        fill=BADGE_TEXT[slot],
        anchor="mm",
        stroke_width=3,
        stroke_fill=BADGE_TEXT[slot],
    )


def build(images: list[bytes]) -> bytes:
    """2 images → 1×2 duel strip, 4 images → 2×2 grid. Returns JPEG bytes."""
    if len(images) not in (2, 4):
        raise ValueError("collage needs 2 or 4 images")
    columns = 2
    rows = len(images) // 2
    badges = DUEL_BADGES if len(images) == 2 else TOURNAMENT_BADGES
    width = columns * CELL + (columns - 1) * GAP
    height = rows * CELL + (rows - 1) * GAP
    canvas = Image.new("RGB", (width, height), BACKGROUND)
    for slot, image_bytes in enumerate(images):
        x = (slot % columns) * (CELL + GAP)
        y = (slot // columns) * (CELL + GAP)
        canvas.paste(_cell(image_bytes), (x, y))
        _badge(canvas, x, y, slot, badges[slot])
    output = BytesIO()
    canvas.save(output, "JPEG", quality=85, optimize=True)
    return output.getvalue()
