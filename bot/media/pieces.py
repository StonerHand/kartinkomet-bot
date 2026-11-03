"""«Pic by pieces»: a piece of one pic, blown up, beside the four pics it may come from.

Left, the piece: a square window of the hidden pic, bigger each stage. Right, the four
candidates whole in a 2×2 grid, each with its letter on the colour of its button."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from bot.media.collage import BACKGROUND, BADGE_COLORS, BADGE_TEXT, CARD, GAP, PAD, RADIUS, _rounded

SIDE = 600  # the piece's square
THUMB = (SIDE - GAP) // 2  # a candidate's square
BADGE = 56  # the letter's square in a candidate's corner
LETTERS = ("A", "B", "C", "D")


def _open(image_bytes: bytes, box: int) -> Image.Image:
    with Image.open(BytesIO(image_bytes)) as source:
        source.draft("RGB", (box * 2, box * 2))
        return source.convert("RGB")


def window(picture: Image.Image, zoom: float, center: tuple[float, float]) -> Image.Image:
    """The square of side zoom × the shorter edge around center (fractions of width and height),
    kept inside the pic."""
    side = max(8, int(min(picture.size) * zoom))
    left = min(max(0, int(center[0] * picture.width - side / 2)), picture.width - side)
    top = min(max(0, int(center[1] * picture.height - side / 2)), picture.height - side)
    return picture.crop((left, top, left + side, top + side))


def _candidate(image_bytes: bytes, slot: int) -> Image.Image:
    cell = Image.new("RGB", (THUMB, THUMB), CARD)
    picture = _open(image_bytes, THUMB)
    picture.thumbnail((THUMB, THUMB), Image.Resampling.LANCZOS)
    cell.paste(picture, ((THUMB - picture.width) // 2, (THUMB - picture.height) // 2))
    draw = ImageDraw.Draw(cell)
    draw.rounded_rectangle((8, 8, 8 + BADGE, 8 + BADGE), 12, fill=BADGE_COLORS[slot])
    color = BADGE_TEXT[slot]
    font = ImageFont.load_default(size=36)
    draw.text((8 + BADGE / 2, 8 + BADGE / 2), LETTERS[slot], font=font, fill=color, anchor="mm",
              stroke_width=1, stroke_fill=color)
    return cell


def board(hidden: bytes, candidates: list[bytes], zoom: float, center: tuple[float, float]) -> bytes:
    """JPEG: the piece of `hidden` at this zoom, then the four candidates (hidden among them)."""
    if len(candidates) != len(LETTERS):
        raise ValueError("the board needs four candidates")
    canvas = Image.new("RGB", (2 * PAD + 2 * SIDE + GAP, 2 * PAD + SIDE), BACKGROUND)
    piece = window(_open(hidden, SIDE), zoom, center).resize((SIDE, SIDE), Image.Resampling.LANCZOS)
    canvas.paste(piece, (PAD, PAD), _rounded((SIDE, SIDE), RADIUS))
    mask = _rounded((THUMB, THUMB), RADIUS // 2)
    for slot, image_bytes in enumerate(candidates):
        x = PAD + SIDE + GAP + (slot % 2) * (THUMB + GAP)
        y = PAD + (slot // 2) * (THUMB + GAP)
        canvas.paste(_candidate(image_bytes, slot), (x, y), mask)
    output = BytesIO()
    canvas.save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()
