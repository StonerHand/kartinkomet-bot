"""Pic captions and footers."""

from html import escape

from bot.core import shop
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
    return f"<i>{' · '.join(parts)}</i>"


def pic_caption(pic: Pic, bucket: str, chat_id: int, uploader: str | None, bounty: int = 0) -> str:
    pool = {"fresh": captions.FRESH, "legend": captions.LEGEND}.get(bucket, captions.CAPTIONS)
    return f"{escape(pick(pool, chat_id))}\n\n{pic_footer(pic, uploader, bounty)}"
