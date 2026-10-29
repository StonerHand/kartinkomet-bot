"""Arena collage: fighters side by side (duel) or in a 2×2 grid (tournament).

Each fighter is a card: a coloured strip with its letter or number on top, the pic below it,
whole and uncovered. The strip carries the same colour as the vote buttons and bars (🟥 🟦 🟩 🟨),
so voters match card, line and button at a glance. All cards of a collage are the same size,
whatever the pics' shapes, so the layout never shifts.
"""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

CELL_WIDTH = 600
STRIP = 64  # the label strip over each pic
PAD = 18  # canvas edge
GAP = 14  # between cards
RADIUS = 22
INSET = 10  # the pic keeps off the card's rounded edges
BODY_HEIGHT = {2: (420, 820), 4: (340, 600)}  # (min, max) pic area per card: duel, tournament
BACKGROUND = (17, 18, 22)
CARD = (34, 36, 43)
# Same colours as the vote bars and buttons: 🟥 🟦 🟩 🟨
BADGE_COLORS = ((229, 57, 53), (30, 136, 229), (67, 160, 71), (253, 216, 53))
BADGE_TEXT = ((255, 255, 255), (255, 255, 255), (255, 255, 255), (33, 33, 33))
DUEL_BADGES = ("A", "B")
TOURNAMENT_BADGES = ("1", "2", "3", "4")
SUPERSAMPLE = 2  # rounded corners are drawn larger and scaled down: Pillow doesn't antialias shapes


def _fit(image_bytes: bytes, box: tuple[int, int] = (CELL_WIDTH, BODY_HEIGHT[2][1])) -> Image.Image:
    with Image.open(BytesIO(image_bytes)) as source:
        source.draft("RGB", box)  # cheap JPEG downscale while decoding
        picture = source.convert("RGB")
    picture.thumbnail(box, Image.Resampling.LANCZOS)
    return picture


def _rounded(size: tuple[int, int], radius: int) -> Image.Image:
    """An antialiased rounded-rectangle mask."""
    width, height = size
    big = Image.new("L", (width * SUPERSAMPLE, height * SUPERSAMPLE), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, width * SUPERSAMPLE - 1, height * SUPERSAMPLE - 1), radius * SUPERSAMPLE, fill=255
    )
    return big.resize(size, Image.Resampling.LANCZOS)


# Evolution frames by stage index (see bot.core.shop.STAGES): beast silver, dragon gold, deity violet.
STAGE_FRAMES = {2: (192, 199, 207), 3: (255, 196, 0), 4: (170, 90, 255)}
STAGE_FRAME_WIDTH = 6
COSMETIC_FRAME_WIDTH = 10


def _card(picture: Image.Image, slot: int, label: str, body: int, frame: tuple | None, frame_width: int) -> Image.Image:
    """One fighter: the strip with its label, the pic centred under it, an optional frame around."""
    card = Image.new("RGB", (CELL_WIDTH, STRIP + body), CARD)
    draw = ImageDraw.Draw(card)
    draw.rectangle((0, 0, CELL_WIDTH, STRIP), fill=BADGE_COLORS[slot])
    font = ImageFont.load_default(size=40)
    color = BADGE_TEXT[slot]
    draw.text((CELL_WIDTH / 2, STRIP / 2), label, font=font, fill=color, anchor="mm", stroke_width=1, stroke_fill=color)
    card.paste(picture, ((CELL_WIDTH - picture.width) // 2, STRIP + (body - picture.height) // 2))
    if frame is None:
        return card
    framed = Image.new("RGB", card.size, frame)
    inner = (CELL_WIDTH - 2 * frame_width, card.height - 2 * frame_width)
    framed.paste(card.resize(inner, Image.Resampling.LANCZOS), (frame_width, frame_width),
                 _rounded(inner, RADIUS - frame_width))
    return framed


def build(images: list[bytes], stages: list[int] | None = None, frames: list[tuple | None] | None = None) -> bytes:
    """2 images → two cards side by side, 4 images → 2×2. Returns JPEG bytes.
    stages: evolution stage per pic; evolved pics get a coloured frame.
    frames: a cosmetic frame colour per pic (from a chest), wider, instead of the stage frame."""
    if len(images) not in (2, 4):
        raise ValueError("collage needs 2 or 4 images")
    low, high = BODY_HEIGHT[len(images)]
    pictures = [_fit(image, (CELL_WIDTH - 2 * INSET, high - 2 * INSET)) for image in images]
    body = max(low, min(high, max(picture.height for picture in pictures) + 2 * INSET))
    labels = DUEL_BADGES if len(images) == 2 else TOURNAMENT_BADGES
    rows = (len(images) + 1) // 2
    card_height = STRIP + body
    width = 2 * PAD + 2 * CELL_WIDTH + GAP
    height = 2 * PAD + rows * card_height + (rows - 1) * GAP
    canvas = Image.new("RGB", (width, height), BACKGROUND)
    mask = _rounded((CELL_WIDTH, card_height), RADIUS)
    for slot, picture in enumerate(pictures):
        frame, frame_width = (STAGE_FRAMES.get(stages[slot]) if stages else None), STAGE_FRAME_WIDTH
        if frames and frames[slot]:
            frame, frame_width = frames[slot], COSMETIC_FRAME_WIDTH
        card = _card(picture, slot, labels[slot], body, frame, frame_width)
        x = PAD + (slot % 2) * (CELL_WIDTH + GAP)
        y = PAD + (slot // 2) * (card_height + GAP)
        canvas.paste(card, (x, y), mask)
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
