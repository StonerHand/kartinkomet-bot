"""Message texts for cards and screens. Pure formatting, no I/O.

Visual language: bold caps header with the key number (timer, verdict), flavour phrase in a
blockquote followed by an empty line (Telegram glues the next line to a quote otherwise),
vote counts first and short emoji bars after them so numbers line up, no empty cells
(they render badly on phones), names without "@" (an @mention pings the person every time).
"""

from html import escape

from bot.core import achievements as rules
from bot.core.arena import DEATH_LOSS_STREAK, DEATH_RATING
from bot.db.repo import Battle, Court, Pic, UserStats
from bot.game import BattleReport, CourtReport, Granted
from bot.texts import arena as arena_texts
from bot.texts import captions, court as court_texts, tops as top_texts, ui
from bot.texts import events as event_texts
from bot.texts.achievements import ACHIEVEMENTS, UNLOCKED
from bot.texts.pick import pick
from bot.tg.keyboards import DUEL_LABELS, TOURNAMENT_LABELS

BAR_CELLS = 5
SLOT_COLORS = ("🟥", "🟦", "🟩", "🟨")
MEDALS = ("🥇", "🥈", "🥉")


def timer(seconds: int) -> str:
    seconds = max(0, seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def bar(count: int, leader: int, color: str) -> str:
    if count <= 0 or leader <= 0:
        return ""
    return "  " + color * max(1, round(BAR_CELLS * count / leader))


def rating(value: float) -> str:
    return f"{value:.0f}"


def delta(before: float, after: float) -> str:
    diff = round(after - before)
    return f"+{diff}" if diff >= 0 else f"−{abs(diff)}"


def who(label: str) -> str:
    return escape(label)


def quote(text: str) -> str:
    """Blockquote plus a blank line after it, so the next line doesn't stick to the quote."""
    return f"<blockquote>{escape(text)}</blockquote>\n"


def plural(value: int, one: str, few: str, many: str) -> str:
    tail = value % 100
    if 11 <= tail <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(value % 10, many)


def ago(seconds: int) -> str:
    if seconds < 3600:
        return "только что"
    hours = seconds // 3600
    if hours < 24:
        return f"{hours} ч назад"
    days = hours // 24
    return f"{days} {plural(days, 'день', 'дня', 'дней')} назад"


# ── pics ───────────────────────────────────────────────────────────────


def pic_footer(pic: Pic, uploader: str | None) -> str:
    parts = [f"⭐ {rating(pic.rating)}"]
    if pic.wins or pic.losses:
        parts.append(f"⚔️ {pic.wins}–{pic.losses}")
    if uploader:
        parts.append(f"📥 {who(uploader)}")
    return f"<i>{' · '.join(parts)}</i>"


def pic_caption(pic: Pic, bucket: str, chat_id: int, uploader: str | None) -> str:
    pool = {"fresh": captions.FRESH, "legend": captions.LEGEND}.get(bucket, captions.CAPTIONS)
    return f"{escape(pick(pool, chat_id))}\n\n{pic_footer(pic, uploader)}"


# ── battles ────────────────────────────────────────────────────────────


def vote_lines(counts: list[int], labels: tuple[str, ...]) -> list[str]:
    leader = max(counts) if counts else 0
    return [
        f"{labels[slot]} <b>{count}</b>{bar(count, leader, SLOT_COLORS[slot])}"
        for slot, count in enumerate(counts)
    ]


def battle_card(battle: Battle, remaining: int) -> str:
    counts = battle.vote_counts()
    total = sum(counts)
    is_duel = battle.kind == "duel"
    labels = DUEL_LABELS if is_duel else TOURNAMENT_LABELS
    head = "⚔️ <b>ДУЭЛЬ</b>" if is_duel else "🏟 <b>ТУРНИР ЧЕТЫРЁХ</b>"
    status_pool = arena_texts.DUEL_STATUS if is_duel else arena_texts.TOURNAMENT_STATUS
    lines = [f"{head} · ⏳ <b>{timer(remaining)}</b>", quote(battle.title)]
    if is_duel and battle.streak > 0:
        lines.append(f"👑 {labels[0]} — чемпионка, серия <b>{battle.streak}</b>")
    lines += vote_lines(counts, labels)
    votes = f"{total} {plural(total, 'голос', 'голоса', 'голосов')}" if total else "голосов пока нет"
    if battle.extended and not total:
        status = f"<b>{escape(pick(event_texts.EXTENDED, battle.chat_id))}</b>"
    else:
        status = f"<i>{escape(pick(status_pool, battle.chat_id))}</i>"
    lines += ["", status, f"🗳 {votes} · жми кнопку"]
    return "\n".join(lines)


def battle_result(report: BattleReport, uploaders: list[str]) -> str:
    """One line per pic, best first: marker, slot, uploader, rating change."""
    battle = report.battle
    is_duel = battle.kind == "duel"
    labels = DUEL_LABELS if is_duel else TOURNAMENT_LABELS
    title = "⚔️ <b>ИТОГ ДУЭЛИ</b>" if is_duel else "🏟 <b>ИТОГ ТУРНИРА</b>"

    if not report.counted:
        return f"{title}\n\n{quote(pick(arena_texts.NOBODY_VOTED, battle.chat_id))}"

    counts = battle.vote_counts()
    total = sum(counts)
    score = " : ".join(str(count) for count in counts) if is_duel else f"{total} {plural(total, 'голос', 'голоса', 'голосов')}"
    lines = [f"{title} · <b>{score}</b>", ""]
    executed_id = report.executed.id if report.executed else None
    order = sorted(range(len(battle.pics)), key=lambda slot: (-counts[slot], slot))
    for slot in order:
        pic = battle.pics[slot]
        if slot == report.winner:
            marker = "👑"
        elif pic.id == executed_id:
            marker = "⚰️"
        elif report.winner is None and counts[slot] == max(counts):
            marker = "🤝"
        else:
            marker = "▫️"
        votes = "" if is_duel else f" · {counts[slot]} {plural(counts[slot], 'голос', 'голоса', 'голосов')}"
        name = f"<b>{who(uploaders[slot])}</b>" if slot == report.winner else who(uploaders[slot])
        change = delta(report.rating_before[slot], report.rating_after[slot])
        lines.append(f"{marker} {labels[slot]} {name}{votes} · ⭐ {rating(report.rating_after[slot])} <i>({change})</i>")
    lines.append("")

    if is_duel:
        pool = arena_texts.DUEL_DRAW if report.winner is None else arena_texts.DUEL_WIN
        lines.append(quote(pick(pool, battle.chat_id)))
        if report.winner is not None and report.streak > 1:
            lines.append(f"🔥 Серия чемпионки: <b>{report.streak}</b>")
        if report.executed:
            lines.append(f"⚰️ <b>{escape(pick(arena_texts.DUEL_EXECUTION, battle.chat_id))}</b>")
            lines.append(
                f"<i>Рейтинг ниже {DEATH_RATING:.0f} или {DEATH_LOSS_STREAK}-е поражение подряд — арена не прощает</i>"
            )
    else:
        pool = arena_texts.TOURNAMENT_DRAW if report.winner is None else arena_texts.TOURNAMENT_WIN
        lines.append(quote(pick(pool, battle.chat_id)))
    return "\n".join(lines).rstrip()


def streak_announcement(milestone: int, streak: int, chat_id: int) -> str:
    pool = {3: arena_texts.STREAK_3, 5: arena_texts.STREAK_5}.get(milestone, arena_texts.STREAK_10)
    wins = plural(streak, "победа", "победы", "побед")
    return f"<b>{escape(pick(pool, chat_id))}</b>\n\n👑 Серия: <b>{streak}</b> {wins} подряд"


# ── courts ─────────────────────────────────────────────────────────────


def court_card(trial: Court, remaining: int, uploader: str) -> str:
    kill, spare = trial.vote_counts()
    leader = max(kill, spare)
    lines = [
        f"⚖️ <b>НАРОДНЫЙ СУД</b> · ⏳ <b>{timer(remaining)}</b>",
        quote(trial.title),
        f"🪓 <b>{kill}</b>{bar(kill, leader, '🟥')}",
        f"🕊 <b>{spare}</b>{bar(spare, leader, '🟩')}",
        "",
        f"<i>{escape(pick(court_texts.STATUS, trial.chat_id))}</i>",
    ]
    if trial.last_word:
        lines += [
            "",
            f"🗣 <b>{escape(pick(court_texts.LAST_WORD_INTRO, trial.chat_id))}</b>",
            quote(trial.last_word),
        ]
    else:
        lines += ["", f"🗣 <i>{who(uploader)}, ответь на это сообщение — это будет последнее слово</i>"]
    return "\n".join(lines)


def court_result(report: CourtReport, uploader: str) -> str:
    trial = report.court
    kill, spare = trial.vote_counts()
    executed = report.verdict == "executed"
    head = "⚰️ <b>ПРИГОВОР: КАЗНЕНА</b>" if executed else "🕊 <b>ПРИГОВОР: ПОМИЛОВАНА</b>"
    pool = court_texts.EXECUTED if executed else court_texts.PARDONED
    lines = [head, f"🪓 <b>{kill}</b> · 🕊 <b>{spare}</b>", "", quote(pick(pool, trial.chat_id))]
    if trial.last_word:
        lines.append(f"<i>Последнее слово: «{escape(trial.last_word)}»</i>")
    lines.append(f"<i>📥 {who(uploader)}" + ("" if executed else " · иммунитет на неделю") + "</i>")
    return "\n".join(lines)


# ── achievements ───────────────────────────────────────────────────────


def achievements_unlocked(granted: Granted, label: str) -> str:
    lines = [f"<b>{escape(pick(UNLOCKED))}</b> · {who(label)}"]
    for code in granted.codes:
        name, description = ACHIEVEMENTS.get(code, (code, ""))
        lines.append(f"<b>{escape(name)}</b>\n<i>{escape(description)}</i>")
    return "\n\n".join(lines)


# ── panel screens ──────────────────────────────────────────────────────


def home(totals: dict[str, int], chat_id: int, live_now: list[str]) -> str:
    lines = [
        "🎛 <b>КАРТИНКОМЕТ</b>",
        quote(pick(ui.MENU_HEADERS, chat_id)),
        f"📦 <b>{totals['alive']}</b> в строю · ⚰️ <b>{totals['executed']}</b> на кладбище",
        f"👀 <b>{totals['shows']}</b> {plural(totals['shows'], 'показ', 'показа', 'показов')}"
        f" · 🤙🏻 <b>{totals['likes']}</b> · 🖕🏻 <b>{totals['dislikes']}</b>",
    ]
    if live_now:
        lines += ["", "🔴 <b>Сейчас идёт</b>", *live_now]
    return "\n".join(lines)


def hall(pics: list[Pic], labels: list[str], record: int) -> str:
    lines = ["🏛 <b>ЗАЛ СЛАВЫ</b>", "<i>Лучшие по рейтингу. 👀 — показать пикчу</i>", ""]
    if not pics:
        lines.append("Пока пусто. Устройте пару дуэлей — тут появятся герои")
    for index, (pic, label) in enumerate(zip(pics, labels)):
        place = MEDALS[index] if index < 3 else f"<b>{index + 1}.</b>"
        streak = f" · 🔥{pic.best_streak}" if pic.best_streak > 1 else ""
        lines.append(f"{place} ⭐ <b>{rating(pic.rating)}</b> · ⚔️ {pic.wins}–{pic.losses}{streak} · {who(label)}")
    if record:
        lines += ["", f"👑 Рекорд серии в чате: <b>{record}</b>"]
    return "\n".join(lines)


def bottom(pics: list[Pic], labels: list[str]) -> str:
    lines = ["🕳 <b>ДНО СКЛАДА</b>", "<i>Худшие по рейтингу. ⚖️ — отправить под суд</i>", ""]
    if not pics:
        lines.append("Дно пустое. Подозрительно")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        lines.append(
            f"<b>{index}.</b> ⭐ <b>{rating(pic.rating)}</b> · ⚔️ {pic.wins}–{pic.losses} · 🖕🏻 {pic.dislikes} · {who(label)}"
        )
    return "\n".join(lines)


REMOVAL_REASONS = {"duel": "пала на арене", "court": "казнена судом", "admin": "удалена админом"}


def graveyard(total: int, pics: list[Pic], labels: list[str], now: int) -> str:
    lines = ["⚰️ <b>КЛАДБИЩЕ</b>", f"<i>Покоится с миром: {total}</i>", ""]
    if not pics:
        lines.append("Пока никто не умер. Скукота")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        reason = REMOVAL_REASONS.get(pic.removed_reason or "", "умерла")
        when = f" · {ago(now - pic.removed_at)}" if pic.removed_at else ""
        lines.append(f"<b>{index}.</b> 🪦 {reason}{when} · {who(label)}")
    return "\n".join(lines)


def top(board: str, rows: list[tuple[str, int]]) -> str:
    lines = [f"<b>{escape(top_texts.BOARD_TITLES[board]).upper()}</b>", ""]
    if not rows:
        lines.append(escape(pick(top_texts.BOARD_EMPTY)))
        return "\n".join(lines)
    unit = top_texts.BOARD_UNITS[board]
    for index, (label, value) in enumerate(rows):
        place = MEDALS[index] if index < 3 else f"<b>{index + 1}.</b>"
        lines.append(f"{place} {who(label)} — <b>{value}</b> {unit}")
        if index == 0:
            lines.append(f"<i>      {escape(pick(top_texts.FIRST_PLACE, board))}</i>")
    if len(rows) > 3:
        lines += ["", f"<i>🐌 {who(rows[-1][0])}: {escape(pick(top_texts.LAST_PLACE, board))}</i>"]
    elif len(rows) > 1:
        lines += ["", f"<i>🥈 {who(rows[1][0])}: {escape(pick(top_texts.PODIUM, board))}</i>"]
    return "\n".join(lines)


def profile(label: str, stats: UserStats, owned: set[str], place: int | None) -> str:
    title_code = rules.upload_title_code(stats.uploads)
    title = ACHIEVEMENTS[title_code][0] if title_code else "🥚 Никто"
    goal = rules.next_upload_goal(stats.uploads)
    rank = f" · {place}-е место" if place else ""
    lines = [
        f"👤 <b>{who(label).upper()}</b>",
        f"<b>{escape(title)}</b>{rank}",
        "",
        f"📥 Загружено: <b>{stats.uploads}</b> · живых {stats.pics_alive}",
        f"🤙🏻 <b>{stats.likes_received}</b> · 🖕🏻 <b>{stats.dislikes_received}</b> на твоих пикчах",
        f"⚰️ Казнено твоих: <b>{stats.pics_executed}</b>",
        f"🔥 Лучшая серия: <b>{stats.best_streak}</b> · 🏛 в зале славы: <b>{stats.legends}</b>",
        f"🪓 Казнил: <b>{stats.kill_votes}</b> · 🕊 спас: <b>{stats.spare_votes}</b>",
    ]
    if goal:
        left = goal.threshold - stats.uploads
        lines.append(f"🎯 До «{escape(ACHIEVEMENTS[goal.code][0])}»: ещё {left} {plural(left, 'пикча', 'пикчи', 'пикч')}")
    lines += ["", f"🏅 Ачивки: <b>{len(owned)}</b> из {len(rules.RULES)}"]
    earned = [ACHIEVEMENTS[code][0] for code in rules.RULE_CODES if code in owned]
    if earned:
        lines.append(f"<blockquote expandable>{escape(chr(10).join(earned))}</blockquote>\n")
    lines.append(f"<i>{escape(pick(top_texts.PROFILE_ROASTS))}</i>")
    return "\n".join(lines)


def upload_hub(is_private: bool) -> str:
    if is_private:
        return (
            "📥 <b>ЗАГРУЗКА</b>\n"
            "Жми кнопку и кидай фото, альбомы, пересылки. Дубли и почти-дубли бот выкинет сам."
        )
    return ui.UPLOAD_PRIVATE_ONLY


def upload_progress(intro: str, added: int, duplicates: int, failed: int) -> str:
    return (
        f"📥 <b>ЗАГРУЗКА</b>\n{quote(intro)}\n"
        f"✅ Добавлено: <b>{added}</b>\n"
        f"♻️ Дубли: <b>{duplicates}</b>\n"
        f"⚠️ Не взял: <b>{failed}</b>"
    )


def admin(totals: dict[str, int], users: int, database: str) -> str:
    return (
        "⚙️ <b>АДМИНКА</b>\n"
        "<i>По расписанию: 🌅 пикча дня в 12:00, ⚖️ суд над худшей в 19:00, "
        "📅 итоги недели в воскресенье в 18:00, 💾 бэкап админам в 04:00</i>\n\n"
        f"📦 Живых: <b>{totals['alive']}</b> · ⚰️ казнено: <b>{totals['executed']}</b>\n"
        f"👥 Юзеров: <b>{users}</b>\n"
        f"🗄 <code>{escape(database)}</code>"
    )
