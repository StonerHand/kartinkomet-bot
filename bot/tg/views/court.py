"""People's court: the trial card, the verdict and the appeal hint."""

from html import escape

from bot.core import court
from bot.db.repo import Court
from bot.services.types import CourtReport
from bot.texts import court as court_texts
from bot.texts.pick import pick, steady
from bot.tg.views.layout import bar, bare, card, cited, money, note, num, timer, who


def court_card(trial: Court, remaining: int, uploader: str) -> str:
    kill, spare = trial.vote_counts()
    leader = max(kill, spare)
    head = "📜 <b>Апелляция</b>" if trial.appeal else "⚖️ <b>Народный суд</b>"
    votes = [
        f"🪓 Казнить · <b>{kill}</b>{bar(kill, leader)}",
        f"🕊 Помиловать · <b>{spare}</b>{bar(spare, leader)}",
    ]
    status = escape(steady(court_texts.STATUS, trial.id, kill + spare))  # a new line with each vote
    rule = "⚖️ Для казни нужно 3 голоса «казнить» и большинство" if trial.appeal else ""
    if trial.last_word:
        intro = bare(steady(court_texts.LAST_WORD_INTRO, trial.id))
        word = f"🗣 <b>Последнее слово</b>\n<i>{escape(intro)}</i>\n{cited(trial.last_word).rstrip()}"
        hint = status
    else:
        word = ""
        hint = f"{status}\n🗣 {who(uploader)}, ответь на это сообщение — это будет последнее слово"
    return card(f"{head} · <b>{timer(remaining)}</b>", trial.title or None, votes, rule, word, note(hint))


def court_result(report: CourtReport, uploader: str, extras: list[str] | None = None) -> str:
    trial = report.court
    kill, spare = trial.vote_counts()
    executed = report.verdict == "executed"
    head = "⚰️ <b>Приговор: казнена</b>" if executed else "🕊 <b>Приговор: помилована</b>"
    if trial.appeal:
        head += " · окончательно" if executed else " · по апелляции"
    pool = court_texts.EXECUTED if executed else court_texts.PARDONED
    facts = [
        f"⚖️ Казнить: <b>{kill}</b> · помиловать: <b>{spare}</b>",
        "📰 <b>Амнистия:</b> казней сегодня нет" if report.amnesty else "",
        f"📜 Залог вернулся: {money(report.bail_back)}" if report.bail_back else "",
    ]
    word = f"🗣 <b>Последнее слово</b>\n{cited(trial.last_word).rstrip()}" if trial.last_word else ""
    footer = f"📥 Загрузчик · <b>{who(uploader)}</b>" + ("" if executed else " · иммунитет на неделю")
    hints = [extra for extra in extras or [] if extra.startswith(NOTE)]
    facts += [extra for extra in extras or [] if not extra.startswith(NOTE)]
    return card(head, pick(pool, trial.chat_id), facts, word, footer, *hints)


NOTE = "<blockquote>"


def appeal_hint(uploader: str, bail: int = court.APPEAL_BAIL) -> str:
    return note(
        f"📜 {who(uploader)} может подать апелляцию за {num(bail)} монет в течение "
        f"{court.APPEAL_WINDOW // 60} минут. На повторном суде для казни нужно 3 голоса"
    )
