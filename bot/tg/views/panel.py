"""Panel screens: home, hall of fame, bottom, graveyard, tops, games, upload, admin."""

from html import escape

from bot.core import economy
from bot.db.repo import Pic
from bot.texts import tops as top_texts
from bot.texts import ui
from bot.texts.pick import pick
from bot.tg.views.layout import MEDALS, ago, card, num, plural, rating, who


def home(totals: dict[str, int], chat_id: int, live_now: list[str], today: str | None = None) -> str:
    lines = [
        "🎛 <b>КАРТИНКОМЕТ</b>",
        f"<i>{escape(pick(ui.MENU_HEADERS, chat_id))}</i>",
        "",
    ]
    if today:
        lines += [today, ""]
    lines += [
        f"📦 <b>{totals['alive']}</b> {plural(totals['alive'], 'пикча', 'пикчи', 'пикч')} в строю",
        f"⚰️ <b>{totals['executed']}</b> на кладбище",
        f"👀 <b>{num(totals['shows'])}</b> {plural(totals['shows'], 'показ', 'показа', 'показов')}",
        f"🤙🏻 <b>{num(totals['likes'])}</b> {plural(totals['likes'], 'лайк', 'лайка', 'лайков')}"
        f" · <b>{num(totals['dislikes'])}</b> {plural(totals['dislikes'], 'дизлайк', 'дизлайка', 'дизлайков')}",
    ]
    if live_now:
        lines += ["", "🔴 <b>Сейчас идёт</b>", *live_now]
    return "\n".join(lines)


def hall(pics: list[Pic], labels: list[str], record: int) -> str:
    lines = ["🏛 <b>ЗАЛ СЛАВЫ</b>", "<i>Рейтинг · автор · победы–поражения. Кнопка с номером — показать</i>", ""]
    if not pics:
        lines.append("Пока пусто. Устройте пару дуэлей — тут появятся герои")
    for index, (pic, label) in enumerate(zip(pics, labels)):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        streak = f" · серия {pic.best_streak}" if pic.best_streak > 1 else ""
        lines.append(f"{place} <b>{rating(pic.rating)}</b>  {who(label)}  <i>{pic.wins}–{pic.losses}{streak}</i>")
    if record:
        lines += ["", f"<i>👑 Рекорд серии в чате: {record}</i>"]
    return "\n".join(lines)


def bottom(pics: list[Pic], labels: list[str]) -> str:
    lines = ["🕳 <b>ДНО СКЛАДА</b>", "<i>Рейтинг · автор · дизлайки. Кнопка с номером — под суд</i>", ""]
    if not pics:
        lines.append("Дно пустое. Подозрительно")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        dislikes = plural(pic.dislikes, "дизлайк", "дизлайка", "дизлайков")
        lines.append(f"{index}. <b>{rating(pic.rating)}</b>  {who(label)}  <i>{pic.dislikes} {dislikes}</i>")
    return "\n".join(lines)


REMOVAL_REASONS = {"duel": "пала на арене", "court": "казнена судом", "admin": "удалена админом"}


def graveyard(total: int, pics: list[Pic], labels: list[str], now: int) -> str:
    recent = ". Последние:" if pics else ""
    lines = ["⚰️ <b>КЛАДБИЩЕ</b>", f"<i>Покоится с миром: {total}{recent}</i>", ""]
    if not pics:
        lines.append("Пока никто не умер. Скукота")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        reason = REMOVAL_REASONS.get(pic.removed_reason or "", "умерла")
        when = f" · {ago(now - pic.removed_at)}" if pic.removed_at else ""
        lines.append(f"{index}. {who(label)}  <i>{reason}{when}</i>")
    return "\n".join(lines)


def top(board: str, rows: list[tuple[str, int]]) -> str:
    title, subtitle = top_texts.BOARD_TITLES[board].split(": ", 1)
    emoji, _, name = title.partition(" ")
    lines = [f"{emoji} <b>{escape(name).upper()}</b>", f"<i>{escape(subtitle.capitalize())}</i>", ""]
    if not rows:
        lines.append(escape(pick(top_texts.BOARD_EMPTY)))
        return "\n".join(lines)
    for index, (label, value) in enumerate(rows):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        unit = plural(value, *top_texts.BOARD_UNITS[board])
        lines.append(f"{place} {who(label)} — <b>{num(value)}</b> {unit}")
    lines += ["", f"<i>🥇 {who(rows[0][0])}: {escape(pick(top_texts.FIRST_PLACE, board))}</i>"]
    if len(rows) > 3:
        lines += ["", f"<i>🐌 {who(rows[-1][0])}: {escape(pick(top_texts.LAST_PLACE, board))}</i>"]
    elif len(rows) > 1:
        lines += ["", f"<i>🥈 {who(rows[1][0])}: {escape(pick(top_texts.PODIUM, board))}</i>"]
    return "\n".join(lines)


def upload_hub(is_private: bool) -> str:
    if is_private:
        return card("📥 <b>ЗАГРУЗКА</b>", "Жми кнопку и кидай фото, альбомы, пересылки. Дубли и почти-дубли бот выкинет сам")
    return ui.UPLOAD_PRIVATE_ONLY


def upload_progress(intro: str, added: int, duplicates: int, failed: int) -> str:
    return card(
        "📥 <b>ЗАГРУЗКА</b>",
        intro,
        [f"✅ Добавлено: <b>{added}</b>", f"♻️ Дубли: <b>{duplicates}</b>", f"⚠️ Не взял: <b>{failed}</b>"],
    )


def admin(totals: dict[str, int], users: int, database: str) -> str:
    return card(
        "⚙️ <b>АДМИНКА</b>",
        "Только для админов",
        [
            f"📦 Живых: <b>{num(totals['alive'])}</b>",
            f"⚰️ Казнено: <b>{num(totals['executed'])}</b>",
            f"👥 Юзеров: <b>{users}</b>",
            f"🗄 <code>{escape(database.rsplit('/', 1)[-1])}</code>",
        ],
        [
            "🕒 <b>Расписание</b>",
            "💾 04:00 — бэкап админам",
            "📰 10:00 — событие дня",
            "🌅 12:00 — пикча дня",
            "👹 16:00 — босс",
            "⚖️ 19:00 — суд над худшей",
            "📅 Вс 18:00 — итоги недели",
        ],
    )


GAMES_SCREEN = (
    "🎮 <b>ИГРЫ</b>\n"
    "<i>Всё, за что капают монеты помимо арены. Казино — отдельной кнопкой в пульте</i>\n"
    "\n"
    "👹 <b>Босс</b> · /boss\n"
    "Пикча-чудовище на 10 минут. Чат бьёт его кнопками, добыча делится по урону. "
    "Приходит сам в 16:00, призвать можно раз в 3 часа\n"
    "\n"
    "🖋 <b>Подпиши пикчу</b> · /caption\n"
    f"Минута на подпись ответом на пикчу, потом анонимное голосование. Победителю +{economy.CAPTION_WIN} монет\n"
    "\n"
    "🎡 <b>Колесо фортуны</b> · /wheel\n"
    "Раз в день бесплатно: монеты, проклятие или благословение твоей пикчи, легенда. 777 — +100 монет\n"
    "\n"
    "🔮 <b>Гороскоп</b> · /horoscope\n"
    "Личная пикча и предсказание, раз в день\n"
    "\n"
    "⚡ <b>Золотая пикча</b>\n"
    f"Иногда выпадает в рандоме. Кто первый нажмёт — тому +{economy.GOLD} монет"
)
