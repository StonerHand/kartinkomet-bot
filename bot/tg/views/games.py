"""Mini-games: caption contest, golden pic, the free wheel, horoscope."""

from html import escape

from bot.core import games as game_rules
from bot.core import economy
from bot.core import shop
from bot.db.repo import Pic
from bot.texts import games as game_texts
from bot.texts.pick import pick
from bot.tg.views.layout import card, money, num, plural, rating, timer, who


def caption_card(game: dict, remaining: int, chat_id: int) -> str:
    entries = game["entries"]
    if game["phase"] == "collect":
        return card(
            f"🖋 <b>ПОДПИШИ ПИКЧУ</b> · <b>{timer(remaining)}</b>",
            pick(game_texts.CAPTION_START, chat_id),
            f"Ответь на это сообщение своей подписью — до {game_rules.CAPTION_MAX_LENGTH} символов, можно переписать.",
            f"✍️ Подписей: <b>{len(entries)}</b> из {game_rules.CAPTION_MAX_ENTRIES}",
        )
    tally: dict[int, int] = {}
    for author in game["votes"].values():
        tally[author] = tally.get(author, 0) + 1
    listing = []
    for index, entry in enumerate(entries, start=1):
        votes = tally.get(entry["user_id"], 0)
        listing.append(
            f"<b>{index}.</b> {escape(entry['text'])}"
            + (f"\n<i>{votes} {plural(votes, 'голос', 'голоса', 'голосов')}</i>" if votes else "")
        )
    return card(
        f"🗳 <b>ЛУЧШАЯ ПОДПИСЬ?</b> · <b>{timer(remaining)}</b>", pick(game_texts.CAPTION_VOTE, chat_id), *listing
    )


def caption_result(game: dict, labels: dict[int, str], chat_id: int) -> str:
    tally: dict[int, int] = {}
    for author in game["votes"].values():
        tally[author] = tally.get(author, 0) + 1
    winner = game.get("winner")
    pool = game_texts.CAPTION_WIN if winner is not None else game_texts.CAPTION_NO_VOTES
    listing = []
    for entry in sorted(game["entries"], key=lambda entry: -tally.get(entry["user_id"], 0)):
        mark = "👑" if entry["user_id"] == winner else "▫️"
        votes = tally.get(entry["user_id"], 0)
        listing.append(
            f"{mark} «{escape(entry['text'])}»\n"
            f"<i>{who(labels.get(entry['user_id'], '?'))} · {votes} {plural(votes, 'голос', 'голоса', 'голосов')}</i>"
        )
    prize = f"🏆 <b>{who(labels.get(winner, '?'))}</b> +{money(economy.CAPTION_WIN)}" if winner is not None else None
    return card("🖋 <b>ИТОГИ: ПОДПИШИ ПИКЧУ</b>", pick(pool, chat_id), *listing, prize)


def caption_cancelled(chat_id: int) -> str:
    return card("🖋 <b>ПОДПИШИ ПИКЧУ</b>", pick(game_texts.CAPTION_CANCELLED, chat_id))


def gold_caption() -> str:
    return card(
        "⚡ <b>ЗОЛОТАЯ ПИКЧА</b>",
        pick(game_texts.GOLD),
        f"<i>Первому — +{money(economy.GOLD)} и ачивка</i>",
    )


def spin_result(label: str, spin: game_rules.Spin, pic: Pic | None, balance: int, chat_id: int) -> str:
    title = game_texts.SPIN_TITLES[spin.kind].split(" ", 1)[1]
    flavour = pick(game_texts.SPIN_RESULTS[spin.kind], chat_id).split(" ", 1)[1]  # phrases open with the emoji
    facts = []
    if spin.coins:
        sign = "+" if spin.coins > 0 else "−"
        facts.append(f"🪙 {sign}{money(abs(spin.coins))} · баланс <b>{num(balance)}</b>")
    hint = None
    if spin.kind in ("curse", "bless"):
        if pic is None:
            facts.append("<i>…но твоих пикч на складе нет, так что мимо</i>")
        else:
            change = -shop.CURSE_RATING if spin.kind == "curse" else game_rules.BLESS_RATING
            sign = "+" if change > 0 else "−"
            facts.append(f"⭐ Твоя пикча: {sign}{abs(change)} рейтинга\n<i>теперь {rating(pic.rating + change)}</i>")
            if spin.kind == "curse":
                hint = "<i>Порчу можно снять за сутки — в лавке под пикчей</i>"
    return card(f"🎡 <b>КОЛЕСО: {title}</b> · {who(label)}", flavour, facts, hint)


def horoscope(label: str, chat_id: int) -> str:
    return card(f"🔮 <b>ГОРОСКОП · {who(label).upper()}</b>", None, escape(pick(game_texts.HOROSCOPE, chat_id)))
