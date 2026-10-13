"""Arena collage: fighters side by side (duel) or in a 2×2 grid (tournament), each with a
small coloured badge, so voters can see which pic is 🅰️/🅱️ or 1–4 in a single message."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

CELL_WIDTH = 640
MAX_CELL_HEIGHT = 800  # tall pics are shrunk to fit; rows are only as tall as their tallest pic
GAP = 6
BACKGROUND = (24, 24, 28)
# Same colours as the vote bars and buttons: 🟥 🟦 🟩 🟨
BADGE_COLORS = ((229, 57, 53), (30, 136, 229), (67, 160, 71), (253, 216, 53))
BADGE_TEXT = ((255, 255, 255), (255, 255, 255), (255, 255, 255), (33, 33, 33))
DUEL_BADGES = ("A", "B")
TOURNAMENT_BADGES = ("1", "2", "3", "4")
BADGE_SIZE = 48  # px on a 640 px cell: readable on a phone without covering the pic
BADGE_MARGIN = 10
SUPERSAMPLE = 4  # Pillow shapes aren't antialiased: draw 4× larger, then scale down


def _fit(image_bytes: bytes) -> Image.Image:
    with Image.open(BytesIO(image_bytes)) as source:
        source.draft("RGB", (CELL_WIDTH, MAX_CELL_HEIGHT))  # cheap JPEG downscale while decoding
        picture = source.convert("RGB")
    picture.thumbnail((CELL_WIDTH, MAX_CELL_HEIGHT), Image.Resampling.LANCZOS)
    return picture


def _badge(slot: int, label: str) -> Image.Image:
    """Antialiased round badge as an RGBA image of BADGE_SIZE px."""
    big = BADGE_SIZE * SUPERSAMPLE
    ring = 2 * SUPERSAMPLE
    badge = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.ellipse((0, 0, big - 1, big - 1), fill=(255, 255, 255, 255))
    draw.ellipse((ring, ring, big - 1 - ring, big - 1 - ring), fill=BADGE_COLORS[slot] + (255,))
    font = ImageFont.load_default(size=int(big * 0.58))
    color = BADGE_TEXT[slot] + (255,)
    draw.text((big / 2, big / 2), label, font=font, fill=color, anchor="mm", stroke_width=3, stroke_fill=color)
    return badge.resize((BADGE_SIZE, BADGE_SIZE), Image.Resampling.LANCZOS)


def build(images: list[bytes]) -> bytes:
    """2 images → 1×2 duel strip, 4 images → 2×2 grid. Returns JPEG bytes."""
    if len(images) not in (2, 4):
        raise ValueError("collage needs 2 or 4 images")
    pictures = [_fit(image) for image in images]
    badges = DUEL_BADGES if len(images) == 2 else TOURNAMENT_BADGES
    rows = [pictures[index : index + 2] for index in range(0, len(pictures), 2)]
    row_heights = [max(picture.height for picture in row) for row in rows]
    width = 2 * CELL_WIDTH + GAP
    height = sum(row_heights) + GAP * (len(rows) - 1)
    canvas = Image.new("RGB", (width, height), BACKGROUND)

    top = 0
    for row_index, row in enumerate(rows):
        for column, picture in enumerate(row):
            slot = row_index * 2 + column
            cell_x = column * (CELL_WIDTH + GAP)
            x = cell_x + (CELL_WIDTH - picture.width) // 2
            y = top + (row_heights[row_index] - picture.height) // 2
            canvas.paste(picture, (x, y))
            badge = _badge(slot, badges[slot])
            canvas.paste(badge, (x + BADGE_MARGIN, y + BADGE_MARGIN), badge)
        top += row_heights[row_index] + GAP

    output = BytesIO()
    canvas.save(output, "JPEG", quality=90, optimize=True)
    return output.getvalue()


GOLD_OUTER = (212, 160, 23)
GOLD_INNER = (255, 223, 110)


def golden_frame(image_bytes: bytes) -> bytes:
    """The pic in a thick gold frame for the 'golden pic' drop."""
    picture = _fit(image_bytes)
    border = max(18, picture.width // 22)
    framed = Image.new("RGB", (picture.width + 2 * border, picture.height + 2 * border), GOLD_OUTER)
    draw = ImageDraw.Draw(framed)
    inset = border // 3
    draw.rectangle(
        (inset, inset, framed.width - 1 - inset, framed.height - 1 - inset), outline=GOLD_INNER, width=max(3, border // 5)
    )
    framed.paste(picture, (border, border))
    output = BytesIO()
    framed.save(output, "JPEG", quality=90, optimize=True)
    return output.getvalue()
