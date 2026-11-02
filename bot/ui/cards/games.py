"""Mini-games: caption contest, golden pic, the free wheel, horoscope."""

from html import escape

from bot.core import games as game_rules
from bot.core import economy
from bot.core import shop
from bot.db.repo import Pic
from bot.texts import games as game_texts
from bot.texts.pick import pick, steady
from bot.tg.ui.views.layout import card, money, note, num, plural, rating, timer, who


def caption_card(game: dict, remaining: int) -> str:
    entries = game["entries"]
    if game["phase"] == "collect":
        return card(
            f"🖋 <b>Подпиши пикчу</b> · <b>{timer(remaining)}</b>",
            steady(game_texts.CAPTION_START, game.get("id")),
            f"✍️ Подписей: <b>{len(entries)}</b> из {game_rules.CAPTION_MAX_ENTRIES}",
            note(f"Ответь на это сообщение своей подписью — до {game_rules.CAPTION_MAX_LENGTH} символов, можно переписать"),
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
        f"🗳 <b>Лучшая подпись?</b> · <b>{timer(remaining)}</b>", steady(game_texts.CAPTION_VOTE, game.get("id")), *listing
    )


def caption_result(game: dict, labels: dict[int, str], chat_id: int, prize: int = economy.CAPTION_WIN) -> str:
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
    won = f"🏆 <b>{who(labels.get(winner, '?'))}</b> +{money(prize)}" if winner is not None else None
    return card("🖋 <b>Итоги: подпиши пикчу</b>", pick(pool, chat_id), *listing, won)


def caption_cancelled(chat_id: int) -> str:
    return card("🖋 <b>Подпиши пикчу</b>", pick(game_texts.CAPTION_CANCELLED, chat_id))


def gold_caption(prize: int = economy.GOLD) -> str:
    return card(
        "⚡ <b>Золотая пикча</b>",
        pick(game_texts.GOLD),
        f"🏆 Первому — +{money(prize)} и ачивка",
    )


def spin_result(label: str, spin: game_rules.Spin, pic: Pic | None, balance: int, chat_id: int) -> str:
    title = game_texts.SPIN_TITLES[spin.kind].split(" ", 1)[1].lower()
    flavour = pick(game_texts.SPIN_RESULTS[spin.kind], chat_id).split(" ", 1)[1]  # phrases open with the emoji
    facts = []
    if spin.coins:
        sign = "+" if spin.coins > 0 else "−"
        facts.append(f"🪙 {sign}{money(abs(spin.coins))} · баланс <b>{num(balance)}</b>")
    hint = None
    if spin.kind in ("curse", "bless"):
        if pic is None:
            facts.append("🫥 …но твоих пикч на складе нет, так что мимо")
        else:
            change = -shop.CURSE_RATING if spin.kind == "curse" else game_rules.BLESS_RATING
            sign = "+" if change > 0 else "−"
            facts.append(f"⭐ Твоя пикча: {sign}{abs(change)} рейтинга\n<i>теперь {rating(pic.rating + change)}</i>")
            if spin.kind == "curse":
                hint = note("Порчу можно снять за сутки — в лавке под пикчей")
    if spin.kind == "chest":
        facts.append("🟫 +1 деревянный сундук")
        hint = note("Открыть — в /quests")
    if spin.kind == "title":
        facts.append(f"🏷 Титул «{escape(spin.prize)}»")
        hint = note("Он теперь в твоём профиле")
    return card(f"🎡 <b>Колесо: {title}</b> · {who(label)}", flavour, facts, hint)


def horoscope(label: str, chat_id: int) -> str:
    return card(f"🔮 <b>Гороскоп</b> · {who(label)}", None, note(escape(pick(game_texts.HOROSCOPE, chat_id))))


# ── whose pic? ─────────────────────────────────────────────────────────


def whose_card(game: dict, remaining: int, reward: int = game_rules.WHOSE_REWARD) -> str:
    answered = len(game["votes"])
    return card(
        f"🕵️ <b>Чья пикча?</b> · <b>{timer(remaining)}</b>",
        steady(game_texts.WHOSE_INTRO, game.get("id")),
        f"✍️ Ответили: <b>{answered}</b>" if answered else "",
        note(f"Угадай, кто её загрузил. Верный ответ — +{money(reward)}, ответ один"),
    )


def whose_result(
    author: str, right: list[str], wrong: int, chat_id: int, reward: int = game_rules.WHOSE_REWARD
) -> str:
    if right:
        verdict = [f"✅ <b>Угадали</b> · каждому +{money(reward)}", ", ".join(who(name) for name in right)]
    else:
        verdict = [f"🤷 {escape(pick(game_texts.WHOSE_NOBODY, chat_id))}"]
    return card(
        "🕵️ <b>Чья пикча?</b> · ответ",
        pick(game_texts.WHOSE_REVEAL, chat_id),
        f"📥 Это пикча <b>{who(author)}</b>",
        verdict,
        f"❌ Мимо: {wrong}" if wrong else "",
    )


# ── higher or lower ────────────────────────────────────────────────────


def hl_reveal(first: Pic, second: Pic) -> str:
    return f"A — <b>{rating(first.rating)}</b> · B — <b>{rating(second.rating)}</b>"


def hl_card(streak: int, record: int, last=None) -> str:
    """A round; `last` is the answer just given (shown as a line above the new question)."""
    previous = f"✅ Верно: {hl_reveal(last.first, last.second)}" if last is not None else ""
    paid = f"<i>+{money(last.paid)} за ответ</i>" if last is not None and last.paid else ""
    return card(
        f"🎯 <b>Выше-ниже</b> · серия <b>{streak}</b>",
        game_texts.HL_QUESTION,
        [previous, paid],
        f"🏆 Рекорд: <b>{record}</b>" if record else "",
    )


def hl_over(answer, chat_id: int, reward: int = game_rules.HL_REWARD) -> str:
    beaten = answer.streak > answer.record_before
    best = max(answer.streak, answer.record_before)
    return card(
        "🎯 <b>Выше-ниже</b> · конец",
        pick(game_texts.HL_RECORD if beaten else game_texts.HL_OVER, chat_id),
        f"❌ Мимо: {hl_reveal(answer.first, answer.second)}",
        f"🏁 Серия: <b>{answer.streak}</b> · рекорд <b>{best}</b>",
        note(f"За верный ответ +{money(reward)}, до {game_rules.HL_PAID_PER_DAY} ответов в день"),
    )
