"""Panel screens: home, hall of fame, bottom, graveyard, tops, games, upload, admin."""

from html import escape

from bot.models.records import Pic
from bot.rules import auction as auction_rules
from bot.rules import economy, seasons
from bot.texts import tops as top_texts
from bot.texts import ui
from bot.texts.pick import pick
from bot.ui.layout import MEDALS, ago, card, money, note, num, plural, rating, who


def season_line(season: str, days_left: int) -> str:
    """'🏆 Сезон · октябрь · ещё 8 дней' — how long until the podium and the coin reset."""
    month = seasons.name(season).split()[0]
    if days_left <= 1:
        return f"🏆 Сезон · {month} · последний день"
    return f"🏆 Сезон · {month} · ещё {days_left} {plural(days_left, 'день', 'дня', 'дней')}"


def help_tab(full: str, tab: str) -> str:
    """One tab of the rules: the help's blocks that open with the tab's emoji, under one title."""
    _, detail, marks = ui.HELP_TABS[tab]
    blocks = [block for block in full.split("\n\n")[1:] if block.startswith(marks)]
    return "\n\n".join([f"❓ <b>Правила</b> · {detail}", *blocks])


def now_block(live_now: list[str]) -> list[str]:
    return ["🔥 <b>Сейчас</b>", *live_now] if live_now else ["🔥 Сейчас тихо — начни дуэль или вытащи пикчу"]


def next_line(next_up: list[str]) -> str:
    return f"⏭ Дальше: {' · '.join(next_up)}" if next_up else "⏭ На сегодня расписание всё"


def home(chat_id: int, live_now: list[str], next_up: list[str], event: str | None = None,
         season: str | None = None) -> str:
    """The group's panel, the same for everyone: what runs, what's next, the day and the season."""
    return card(
        "🎛 <b>Картинкомет</b>",
        pick(ui.MENU_HEADERS, chat_id),
        now_block(live_now),
        next_line(next_up),
        [line for line in (event, season) if line],
        note("«Мой пульт» — твои монеты, уровень и то, что ты ещё не забрал сегодня. Видно только тебе"),
    )


def home_personal(label: str, coins: int, earned: int, live_now: list[str], left: list[str], next_up: list[str],
                  chat_id: int) -> str:
    """One player's panel: their coins and level first, then the chat, then their day."""
    level, upcoming = economy.level_for(earned), economy.next_level(earned)
    if upcoming is None:
        progress = "вершина"
    else:
        share = round(100 * (earned - level.threshold) / (upcoming.threshold - level.threshold))
        progress = f"<code>{economy.progress(earned, cells=6)}</code> {share}%"
    day = ["✅ <b>Тебе сегодня</b>", *[f"▫️ {what}" for what in left]] if left else ["✅ Всё на сегодня забрано"]
    return card(
        f"🎛 <b>Пульт</b> · {who(label)}",
        pick(ui.MENU_HEADERS, chat_id),
        [f"🪙 {money(coins)}", f"{level.name} · {progress}"],
        now_block(live_now),
        day,
        next_line(next_up),
    )


def hall(pics: list[Pic], labels: list[str], record: int) -> str:
    lines = ["🏛 <b>Зал славы</b>", "<i>Рейтинг · автор · победы–поражения. Кнопка с номером — показать</i>", ""]
    if not pics:
        lines.append("🕸 Пока пусто. Устройте пару дуэлей — тут появятся герои")
    for index, (pic, label) in enumerate(zip(pics, labels)):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        streak = f" · серия {pic.best_streak}" if pic.best_streak > 1 else ""
        lines.append(f"{place} <b>{rating(pic.rating)}</b>  {who(label)}  <i>{pic.wins}–{pic.losses}{streak}</i>")
    if record:
        lines += ["", f"<i>👑 Рекорд серии в чате: {record}</i>"]
    return "\n".join(lines)


def bottom(pics: list[Pic], labels: list[str]) -> str:
    lines = ["🕳 <b>Дно склада</b>", "<i>Рейтинг · автор · дизлайки. Кнопка с номером — под суд</i>", ""]
    if not pics:
        lines.append("🕸 Дно пустое. Подозрительно")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        dislikes = plural(pic.dislikes, "дизлайк", "дизлайка", "дизлайков")
        lines.append(f"{index}. <b>{rating(pic.rating)}</b>  {who(label)}  <i>{pic.dislikes} {dislikes}</i>")
    return "\n".join(lines)


REMOVAL_REASONS = {"duel": "арена", "court": "суд", "admin": "админ"}


def graveyard(total: int, pics: list[Pic], labels: list[str], now: int) -> str:
    recent = ". Последние:" if pics else ""
    lines = ["⚰️ <b>Кладбище</b>", f"<i>Покоится с миром: {total}{recent}</i>", ""]
    if not pics:
        lines.append("🕸 Пока никто не умер. Скукота")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        reason = REMOVAL_REASONS.get(pic.removed_reason or "", "склад")
        when = f", {ago(now - pic.removed_at)}" if pic.removed_at else ""
        lines.append(f"{index}. {who(label)} · <i>{reason}{when}</i>")
    return "\n".join(lines)


def top(board: str, rows: list[tuple[str, int]], week: bool = False) -> str:
    """week: the board counted over the last seven days (only boards in WEEK_SUBTITLES have one)."""
    title, subtitle = top_texts.BOARD_TITLES[board].split(": ", 1)
    emoji, _, name = title.partition(" ")
    head = f"{emoji} <b>{escape(name[0].upper() + name[1:])}</b>"
    if week:
        head, subtitle = f"{head} · неделя", top_texts.WEEK_SUBTITLES[board]
    lines = [head, f"<i>{escape(subtitle[0].upper() + subtitle[1:])}</i>", ""]
    if not rows:
        lines.append(f"🕸 {escape(pick(top_texts.BOARD_EMPTY))}")
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
        return card("📥 <b>Загрузка</b>", "Жми кнопку и кидай фото, альбомы, пересылки. Дубли и почти-дубли бот выкинет сам")
    return ui.UPLOAD_PRIVATE_ONLY


def upload_progress(intro: str, added: int, duplicates: int, failed: int) -> str:
    return card(
        "📥 <b>Загрузка</b>",
        intro,
        [f"✅ Добавлено: <b>{added}</b>", f"♻️ Дубли: <b>{duplicates}</b>", f"⚠️ Не взял: <b>{failed}</b>"],
    )


def admin(totals: dict[str, int], users: int, database: str, wallet: int = 0, factor: float = 1.0,
          duplicates: tuple[int, int] = (0, 0), private: bool = False) -> str:
    """wallet: the average wallet of the money pool (active players, admins included); factor:
    what every price, reward and fine is multiplied by because of it. private: opened in a private
    chat, where the chat's switches (events, widgets) don't show: the card says where they are."""
    return card(
        "⚙️ <b>Админка</b>",
        "Только для админов",
        [
            f"📦 Живых: <b>{num(totals['alive'])}</b>",
            f"⚰️ Казнено: <b>{num(totals['executed'])}</b>",
            f"👥 Юзеров: <b>{users}</b>",
            f"🧹 Дублей убрано: <b>{num(duplicates[1])}</b>" if duplicates[1] else "",
            f"🔍 Ждут проверки на дубли: <b>{num(duplicates[0])}</b>" if duplicates[0] else "",
            f"🗄 <code>{escape(database.rsplit('/', 1)[-1])}</code>",
        ],
        [
            "💰 <b>Экономика</b>",
            f"средний кошелёк <b>{num(wallet)}</b>",
            f"все суммы ×<b>{_factor(factor)}</b>",
        ],
        [
            "🕒 <b>Расписание</b>",
            "💾 04:00 — бэкап админам",
            "📰 10:00 — событие дня",
            "📸 11:00 — тема дня",
            "🌅 12:00 — пикча дня",
            "🗳 13:00 — кто из нас",
            "🔨 15:00 — аукцион до 22:00",
            "👹 16:00 — босс, в субботу рейд",
            "💸 18:00 — великий передел",
            "⚖️ 19:00 — суд над худшей",
            "🎬 21:00 — вечернее шоу",
            "📅 Вс 18:00 — итоги недели",
            "🚩 Пн 10:00 — команды недели",
            "🎌 Вс 22:00 — итог команд",
            "🏁 1-е число — итоги сезона",
        ],
        "🧩 События и виджеты включаются в /admin группового чата" if private else "",
    )


def today_screen(event: str, plan: list[tuple[int, str, str, bool]], mine: list[tuple[str, bool]],
                 running: list[str], team: list[str] | None = None) -> str:
    """plan: (hour, emoji, what, already passed); mine: (what, done today) for the viewer; team:
    the team week's score lines, if one is on."""
    schedule = [f"{'✅' if passed else emoji} {hour}:00 · {escape(what)}" for hour, emoji, what, passed in plan]
    return card(
        "📅 <b>Сегодня в чате</b>",
        event,
        ["🔥 <b>Сейчас идёт</b>", *running] if running else "",
        ["🕒 <b>Расписание</b>", *schedule],
        team or "",
        ["👤 <b>Твоё на сегодня</b>", *[f"{'✅' if done else '▫️'} {what}" for what, done in mine]] if mine else "",
        note("Галочка — уже было или уже забрано. Кнопки ниже — то, что сегодня ещё ждёт тебя"),
    )


def _factor(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") if value < 10 else num(round(value))


def games_screen() -> str:
    """Every game on one line, grouped by how it plays: what it is and how to start it. The rules
    live in «Правила» → «Игры»; the buttons below follow the same order."""
    return card(
        "🎮 <b>Игры</b>",
        "Всё, за что капают монеты помимо арены",
        [
            "🗣 <b>Поболтать</b>",
            "🗳 Кто из нас · /who · 13:00",
            "🐊 Крокодил пикчами · /croc",
            "🎭 Шпион · /spy",
            "🤝 Спор на монеты · /bet",
        ],
        [
            "⚡ <b>Быстрые</b>",
            "💣 Бомба · /bomb",
            "🧨 Сапёр · /mines",
            "🔐 Сейф · /safe",
            "🧩 Пикча по кусочку · /pieces",
            "🕵️ Чья пикча · /whose",
            "🖋 Подпиши пикчу · /caption",
            "👹 Босс · /boss · 16:00",
        ],
        [
            "⏰ <b>По часам</b>",
            "📸 Тема дня · 11:00",
            f"🔨 Аукцион · {auction_rules.OPEN_HOUR}:00–{auction_rules.CLOSE_HOUR}:00",
            "🎬 Шоу · /heist · /cup · 21:00",
            "🚩 Командная неделя · пн–вс",
        ],
        "🎯 Выше-ниже · /higher · в личке",
        note("Кнопки ниже запускают игру в этом чате. Колесо и гороскоп — в /today. "
             "Как играть в каждую — «Правила» → «Игры»"),
    )


PEOPLE_SCREEN = (
    "👥 <b>Люди</b>\n"
    "<i>Монеты ходят по рукам. Жми кнопку — бот спросит кого и сколько, видно будет только тебе</i>\n"
    "\n"
    "😈 <b>Ограбить</b> · /rob\n"
    "Шанс 40%. Провал — штраф жертве и обезьянник\n"
    "\n"
    "🎁 <b>Подарить</b> · /give\n"
    "Любую сумму кому угодно\n"
    "\n"
    "🤺 <b>Вызов</b> · /challenge\n"
    "Пикчи двух игроков дерутся, чат голосует, банк — победителю\n"
    "\n"
    "🎲 <b>1 на 1</b> · /pvp\n"
    "Кости против человека, без казино. Дартс и кегли — /pvp 200 дартс\n"
    "\n"
    "✊ <b>Камень, ножницы, бумага</b> · /rps\n"
    "Оба выбирают втайне, бот открывает разом. Банк — победителю\n"
    "\n"
    "❌ <b>Крестики-нолики</b> · /ttt\n"
    "Партия на ставку, минута на ход\n"
    "\n"
    "💍 <b>Свадьба</b> · /marry · /divorce\n"
    "+20% к бонусу дня, если оба забрали его в один день. Развод — монеты пополам"
)


def admin_stats(usage: dict[str, int]) -> str:
    """The admin's weekly picture: who plays and which mechanics live. Sections with a title and
    two numbers a line, so even five-digit counts fit a phone."""

    def n(key: str) -> str:
        return f"<b>{num(usage.get(key, 0))}</b>"

    return card(
        "📊 <b>Статистика · 7 дней</b>",
        "Чем живёт чат",
        ["👥 <b>Люди</b>", f"сегодня {n('players_today')} · неделя {n('players_week')}",
         f"загрузок {n('uploads')} · лайков {n('likes')}"],
        ["⚔️ <b>Арена и суды</b>", f"дуэли {n('duels')} · турниры {n('tournaments')}",
         f"суды {n('courts')} · вызовы {n('challenges')}", f"кости 1 на 1 {n('dice_duels')}"],
        ["👹 <b>Боссы</b>", f"обычные {n('bosses')} · рейды {n('raids')}", f"побед {n('bosses_won')}"],
        ["🎮 <b>Игры</b>", f"казино {n('casino')} · колесо {n('spin')}", f"гороскоп {n('horoscope')} · подписи {n('captions')}",
         f"чья пикча {n('whose')} · выше-ниже {n('higher')}"],
        ["🗳 <b>Игры чата</b>", f"кто из нас {n('round_who')} · бомба {n('round_bomb')}",
         f"крокодил {n('round_croc')} · споры {n('round_bet')}", f"шпион {n('round_spy')} · сапёр {n('round_mines')}",
         f"сейф {n('round_safe')} · кусочки {n('round_piece')}",
         f"шоу <b>{num(usage.get('round_heist', 0) + usage.get('round_cup', 0))}</b> · тема {n('round_theme')}",
         f"аукцион {n('round_auction')}"],
        ["🛒 <b>Экономика</b>", f"бонус дня {n('daily')} · покупки {n('purchases')}",
         f"подарки {n('gifts')} · грабежи {n('robberies')}"],
    )
