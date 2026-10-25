"""Seasons: the monthly results, the last-day warning, the hall of seasons."""

from html import escape

from bot.core import seasons
from bot.texts import seasons as texts
from bot.texts.pick import pick
from bot.tg.views.layout import MEDALS, card, note, num, plural, who

PLACE_WORDS = ("победа", "второе место", "третье место")


def points(score: int) -> str:
    return f"<b>{num(score)}</b> {plural(score, 'очко', 'очка', 'очков')}"


def podium_lines(podium: list[tuple[str, int]]) -> list[str]:
    """[(label, score)] → '🥇 name — 1 234 очка'."""
    return [f"{MEDALS[place]} {who(label)} — {points(score)}" for place, (label, score) in enumerate(podium)]


def season_results(season: str, podium: list[tuple[str, int]], starter: int, chat_id: int) -> str:
    following = seasons.name(seasons.next_season(season)).split()[0]
    return card(
        f"🏁 <b>Итоги сезона</b> · {escape(seasons.name(season))}",
        pick(texts.RESULTS, chat_id),
        podium_lines(podium) or [f"🕸 {texts.NOBODY}"],
        f"🪙 Монеты сгорели: все начинают с <b>{num(starter)}</b>",
        note(f"Тройка лучших носит значок сезона в профиле навсегда. Новый сезон — {following}"),
    )


def season_warning(season: str, podium: list[tuple[str, int]], starter: int, chat_id: int) -> str:
    return card(
        f"⏳ <b>Последний день сезона</b> · {escape(seasons.name(season))}",
        pick(texts.WARNING, chat_id),
        f"🕛 В полночь монеты сгорят, все начнут с <b>{num(starter)}</b>",
        ["🏆 <b>Сейчас в тройке</b>", *podium_lines(podium)] if podium else "",
        note(escape(texts.RULES)),
    )


def seasons_hall(current: str, live: list[tuple[str, int]], past: list[tuple[str, list[tuple[str, int]]]]) -> str:
    """live: the running season's top three; past: finished seasons with their podiums."""
    blocks = [["📅 <b>" + escape(seasons.name(current).capitalize()) + "</b> · идёт", *podium_lines(live)]]
    if not live:
        blocks[0].append(f"<i>{texts.NOBODY}</i>")  # under the season's title: its description
    for season, podium in past:
        blocks.append(["🏆 <b>" + escape(seasons.name(season).capitalize()) + "</b>", *podium_lines(podium)])
    return card("🏆 <b>Зал сезонов</b>", pick(texts.HALL), *blocks, note(escape(texts.RULES)))


def season_badges(podiums: list[tuple[str, int]]) -> list[str]:
    """A player's podiums for the profile: '🥇 Октябрь 2026 · победа'."""
    return [
        f"{MEDALS[place - 1]} {escape(seasons.name(season).capitalize())} · {PLACE_WORDS[place - 1]}"
        for season, place in podiums
        if 1 <= place <= len(MEDALS)
    ]
