"""People's court: the trial card, the verdict and the appeal hint."""

from html import escape

from bot.core import court
from bot.db.repo import Court
from bot.services.types import CourtReport
from bot.texts import court as court_texts
from bot.texts.pick import pick
from bot.tg.views.layout import bar, bare, card, cited, money, num, timer, who


def court_card(trial: Court, remaining: int, uploader: str) -> str:
    kill, spare = trial.vote_counts()
    leader = max(kill, spare)
    head = "📜 <b>АПЕЛЛЯЦИЯ</b>" if trial.appeal else "⚖️ <b>НАРОДНЫЙ СУД</b>"
    votes = [
        f"🪓 Казнить · <b>{kill}</b>{bar(kill, leader, '🟥')}",
        f"🕊 Помиловать · <b>{spare}</b>{bar(spare, leader, '🟩')}",
    ]
    status = f"<i>{escape(pick(court_texts.STATUS, trial.chat_id))}</i>"
    rule = "⚖️ Для казни нужно 3 голоса «казнить» и большинство" if trial.appeal else ""
    if trial.last_word:
        intro = bare(pick(court_texts.LAST_WORD_INTRO, trial.chat_id))
        word = f"🗣 <b>Последнее слово</b>\n<i>{escape(intro)}</i>\n{cited(trial.last_word).rstrip()}"
    else:
        word = f"🗣 <i>{who(uploader)}, ответь на это сообщение — это будет последнее слово</i>"
    return card(f"{head} · <b>{timer(remaining)}</b>", trial.title or None, votes, rule, status, word)


def court_result(report: CourtReport, uploader: str, extras: list[str] | None = None) -> str:
    trial = report.court
    kill, spare = trial.vote_counts()
    executed = report.verdict == "executed"
    head = "⚰️ <b>ПРИГОВОР: КАЗНЕНА</b>" if executed else "🕊 <b>ПРИГОВОР: ПОМИЛОВАНА</b>"
    if trial.appeal:
        head += " · окончательно" if executed else " · по апелляции"
    pool = court_texts.EXECUTED if executed else court_texts.PARDONED
    facts = [
        f"⚖️ Казнить: <b>{kill}</b> · помиловать: <b>{spare}</b>",
        "📰 <b>Амнистия:</b> сегодня суд никого не казнит" if report.amnesty else "",
        f"📜 Залог {money(report.bail_back)} вернулся загрузчику" if report.bail_back else "",
    ]
    word = f"<i>Последнее слово: «{escape(trial.last_word)}»</i>" if trial.last_word else ""  # can be long: alone
    footer = f"<i>📥 {who(uploader)}" + ("" if executed else " · иммунитет на неделю") + "</i>"
    return card(head, pick(pool, trial.chat_id), facts, word, *(extras or []), footer)


def appeal_hint(uploader: str, bail: int = court.APPEAL_BAIL) -> str:
    return (
        f"<i>{who(uploader)} может подать апелляцию за {num(bail)} монет в течение "
        f"{court.APPEAL_WINDOW // 60} минут. На повторном суде для казни нужно 3 голоса</i>"
    )
