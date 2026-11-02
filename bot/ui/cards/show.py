"""The evening show: the bank heist's live card, the big cup's intro and champion."""

from bot.models.records import Pic
from bot.rules import show
from bot.texts import show as texts
from bot.texts.pick import pick, steady
from bot.ui.layout import card, duration, money, note, timer, who


def crew_lines(crew: list[tuple[str, str]]) -> list[str]:
    """(name, role) → '💻 взломщик · name'."""
    return [f"{texts.ROLES[role]} · {who(name)}" for name, role in crew]


def heist_log(log: list[tuple[str, int, bool]]) -> list[str]:
    return [f"{'✅' if success else '🚨'} {texts.EVENTS[event][1][option].split(' ', 1)[1]}"
            for event, option, success in log]


def heist_card(stage: int, crew: list[tuple[str, str]], remaining: int, events: list[str],
               log: list[tuple[str, int, bool]], votes: tuple[int, int] = (0, 0), round_id: str = "") -> str:
    """Recruiting (stage 0) or a stage's vote."""
    if stage == 0:
        return card(
            f"🏦 <b>Ограбление</b> · сбор · <b>{timer(remaining)}</b>",
            steady(texts.HEIST_RECRUIT, round_id),
            ["👥 <b>Банда</b>", *crew_lines(crew)] if crew else "👥 Пока никого",
            note(f"Жми «В деле»: от {show.MIN_CREW} до {show.MAX_CREW} человек, роли раздаются по очереди. "
                 f"Три этапа, на каждом банда голосует, как действовать. Чисто — каждому по куску, "
                 f"провал — все в обезьянник"),
        )
    event = events[stage - 1]
    what, labels = texts.EVENTS[event]
    first, second = show.EVENTS[event]
    words = [label.split(" ", 1)[1] for label in labels]  # the buttons' emoji stay on the buttons
    return card(
        f"🏦 <b>Ограбление</b> · этап {stage}/{show.STAGES} · <b>{timer(remaining)}</b>",
        what,
        heist_log(log),
        [f"{mark} {word} · <b>{votes[index]}</b>" for index, (mark, word) in enumerate(zip(("1️⃣", "2️⃣"), words))],
        ["👥 <b>Банда</b>", *crew_lines(crew)],
        note(f"Решает большинство банды, ничья — монетка. «{words[0]}» надёжнее {texts.ROLE_WITH[first.role]} "
             f"в банде, «{words[1]}» — {texts.ROLE_WITH[second.role]}"),
    )


def heist_result(kind: str, crew: list[tuple[str, str]], log: list[tuple[str, int, bool]], loot: int,
                 jail_seconds: int, chat_id: int) -> str:
    if kind == "cancelled":
        return card("🏦 <b>Ограбление</b> · отменено", pick(texts.HEIST_CANCELLED, chat_id),
                    note(f"Нужно хотя бы {show.MIN_CREW} человека. Следующее шоу — завтра в {show.SHOW_HOUR}:00"))
    if kind == "busted":
        verdict = f"🚔 Вся банда в обезьяннике на {duration(jail_seconds)}"
        head, flavour = "🏦 <b>Ограбление</b> · провал", pick(texts.HEIST_BUSTED, chat_id)
    else:
        verdict = f"💰 Каждому +{money(loot)}"
        head, flavour = "🏦 <b>Ограбление</b> · чисто", pick(texts.HEIST_CLEAN, chat_id)
    return card(head, flavour, heist_log(log), verdict, ["👥 <b>Банда</b>", *crew_lines(crew)])


def cup_intro(uploaders: list[str], chat_id: int, prize: int = show.CUP_PRIZE) -> str:
    return card(
        "🏆 <b>Большой турнир</b>",
        pick(texts.CUP_INTRO, chat_id),
        f"🖼 {show.CUP_SIZE} пикч · четвертьфинал, полуфинал, финал",
        f"📥 Пикчи от: {', '.join(who(name) for name in uploaders)}" if uploaders else "",
        note(f"Каждый матч — дуэль на {show.CUP_DUEL_SECONDS} секунд, голосуй и ставь как обычно. "
             f"Следующий матч начнётся сам. Загрузчику чемпионки — {money(prize)} и почёт"),
    )


def cup_champion(pic: Pic, uploader: str, prize: int, chat_id: int) -> str:
    return card(
        "🏆 <b>Чемпионка турнира</b>",
        pick(texts.CUP_CHAMPION, chat_id),
        f"📥 Загрузка <b>{who(uploader)}</b>" + (f" · +{money(prize)}" if prize else ""),
        f"📈 Рейтинг {round(pic.rating)} · +{show.CUP_RATING_BONUS} за кубок",
    )
