"""Pic captions and footers."""

from html import escape

from bot.core import progress, shop
from bot.db.repo import Pic
from bot.texts import captions
from bot.texts.pick import pick
from bot.tg.views.layout import num, rating, who


def pic_footer(pic: Pic, uploader: str | None, bounty: int = 0) -> str:
    stage = shop.stage(pic.wins)
    parts = [f"{stage.emoji} {stage.name}", f"рейтинг {rating(pic.rating)}"]
    if pic.wins or pic.losses:
        parts.append(f"бои {pic.wins}–{pic.losses}")
    if uploader:
        parts.append(f"от {who(uploader)}")
    if bounty:
        parts.append(f"за голову {num(bounty)}")
    if pic.frame in progress.FRAMES:
        parts.append(f"в {progress.FRAMES[pic.frame][0]} рамке")
    return f"<i>{' · '.join(parts)}</i>"


def pic_caption(pic: Pic, bucket: str, chat_id: int, uploader: str | None, bounty: int = 0) -> str:
    pool = {"fresh": captions.FRESH, "legend": captions.LEGEND}.get(bucket, captions.CAPTIONS)
    line = escape(pick(pool, chat_id))
    if pool is captions.CAPTIONS:
        line = f"<i>{line}</i>"  # the pic's own voice, like a card's flavour line
    return f"{line}\n\n{pic_footer(pic, uploader, bounty)}"
