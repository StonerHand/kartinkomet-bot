"""Message texts for cards and screens. Pure formatting, no I/O."""

from html import escape

from bot.core import achievements as rules
from bot.core.arena import DEATH_LOSS_STREAK, DEATH_RATING
from bot.db.repo import Battle, Court, Pic, UserStats
from bot.game import BattleReport, CourtReport, Granted
from bot.texts import arena as arena_texts
from bot.texts import captions, court as court_texts, tops as top_texts, ui
from bot.texts.achievements import ACHIEVEMENTS, UNLOCKED
from bot.texts.pick import pick
from bot.tg.keyboards import DUEL_LABELS, TOURNAMENT_LABELS

BAR_WIDTH = 8


def timer(seconds: int) -> str:
    seconds = max(0, seconds)
    return f"⏱ {seconds // 60}:{seconds % 60:02d}"


def bar(count: int, total: int) -> str:
    filled = round(BAR_WIDTH * count / total) if total else 0
    return "▰" * filled + "▱" * (BAR_WIDTH - filled)


def rating(value: float) -> str:
    return f"{value:.0f}"


def delta(before: float, after: float) -> str:
    diff = round(after - before)
    return f"+{diff}" if diff >= 0 else str(diff)


def who(label: str) -> str:
    return escape(label)


# ── pics ───────────────────────────────────────────────────────────────


def pic_caption(pic: Pic, bucket: str, chat_id: int, uploader: str | None) -> str:
    if bucket == "fresh":
        line = pick(captions.FRESH, chat_id)
    elif bucket == "legend":
        line = pick(captions.LEGEND, chat_id)
    else:
        line = pick(captions.CAPTIONS, chat_id)
    parts = [escape(line)]
    if uploader:
        parts.append(f"<i>📥 {who(uploader)} · ⭐ {rating(pic.rating)}</i>")
    return "\n\n".join(parts)


# ── battles ────────────────────────────────────────────────────────────


def battle_card(battle: Battle, remaining: int) -> str:
    counts = battle.vote_counts()
    total = sum(counts)
    labels = DUEL_LABELS if battle.kind == "duel" else TOURNAMENT_LABELS
    head = "⚔️ Дуэль" if battle.kind == "duel" else "🏟 Турнир четырёх"
    status_pool = (
        arena_texts.DUEL_STATUS if battle.kind == "duel" else arena_texts.TOURNAMENT_STATUS
    )
    lines = [f"<b>{head}</b>", escape(battle.title), ""]
    if battle.kind == "duel" and battle.streak > 0:
        lines.append(f"👑 {labels[0]} — чемпионка, серия {battle.streak}")
    for slot, pic in enumerate(battle.pics):
        lines.append(f"{labels[slot]} {bar(counts[slot], total)} <b>{counts[slot]}</b> · ⭐ {rating(pic.rating)}")
    lines += ["", f"<i>{escape(pick(status_pool, battle.id))}</i>", timer(remaining)]
    return "\n".join(lines)


def battle_result(report: BattleReport) -> str:
    battle = report.battle
    labels = DUEL_LABELS if battle.kind == "duel" else TOURNAMENT_LABELS
    counts = battle.vote_counts()
    head = "⚔️ Дуэль окончена" if battle.kind == "duel" else "🏟 Турнир окончен"
    lines = [f"<b>{head}</b>", ""]

    if not report.counted:
        lines.append(escape(pick(arena_texts.NOBODY_VOTED, battle.chat_id)))
        return "\n".join(lines)

    for slot, pic in enumerate(battle.pics):
        crown = " 👑" if slot == report.winner else ""
        dead = " ⚰️" if report.executed and report.executed.id == pic.id else ""
        lines.append(
            f"{labels[slot]} <b>{counts[slot]}</b> · ⭐ {rating(report.rating_after[slot])} "
            f"({delta(report.rating_before[slot], report.rating_after[slot])}){crown}{dead}"
        )
    lines.append("")

    if battle.kind == "duel":
        if report.winner is None:
            lines.append(escape(pick(arena_texts.DUEL_DRAW, battle.chat_id)))
        else:
            lines.append(escape(pick(arena_texts.DUEL_WIN, battle.chat_id)))
            if report.streak > 1:
                lines.append(f"🔥 Серия: <b>{report.streak}</b>")
        if report.executed:
            lines += ["", "<b>⚰️ " + escape(pick(arena_texts.DUEL_EXECUTION, battle.chat_id)) + "</b>"]
            lines.append(
                f"<i>Рейтинг ниже {DEATH_RATING:.0f} или {DEATH_LOSS_STREAK} поражения подряд — арена не прощает</i>"
            )
    else:
        pool = arena_texts.TOURNAMENT_DRAW if report.winner is None else arena_texts.TOURNAMENT_WIN
        lines.append(escape(pick(pool, battle.chat_id)))
    return "\n".join(lines)


def streak_announcement(milestone: int, streak: int, chat_id: int) -> str:
    pool = {3: arena_texts.STREAK_3, 5: arena_texts.STREAK_5}.get(milestone, arena_texts.STREAK_10)
    return f"<b>{escape(pick(pool, chat_id))}</b>\nСерия: {streak}"


# ── courts ─────────────────────────────────────────────────────────────


def court_card(trial: Court, remaining: int, uploader: str) -> str:
    kill, spare = trial.vote_counts()
    total = kill + spare
    lines = [
        "<b>⚖️ Народный суд</b>",
        escape(trial.title),
        "",
        f"Загрузчик: {who(uploader)}",
        f"🪓 {bar(kill, total)} <b>{kill}</b>",
        f"🕊 {bar(spare, total)} <b>{spare}</b>",
        "",
        f"<i>{escape(pick(court_texts.STATUS, trial.id))}</i>",
        timer(remaining),
    ]
    if trial.last_word:
        lines += ["", escape(pick(court_texts.LAST_WORD_INTRO, trial.id)), f"«{escape(trial.last_word)}»"]
    else:
        lines += ["", "<i>Загрузчик может ответить на это сообщение — это будет последнее слово</i>"]
    return "\n".join(lines)


def court_result(report: CourtReport, uploader: str) -> str:
    trial = report.court
    kill, spare = trial.vote_counts()
    pool = court_texts.EXECUTED if report.verdict == "executed" else court_texts.PARDONED
    head = "⚰️ Казнена" if report.verdict == "executed" else "🕊 Помилована"
    lines = [
        f"<b>⚖️ Приговор: {head}</b>",
        "",
        f"🪓 {kill} · 🕊 {spare}",
        f"Загрузчик: {who(uploader)}",
        "",
        escape(pick(pool, trial.chat_id)),
    ]
    if trial.last_word:
        lines += ["", f"<i>Последнее слово: «{escape(trial.last_word)}»</i>"]
    return "\n".join(lines)


# ── achievements ───────────────────────────────────────────────────────


def achievement_lines(codes: list[str]) -> list[str]:
    result = []
    for code in codes:
        name, description = ACHIEVEMENTS.get(code, (code, ""))
        result.append(f"<b>{escape(name)}</b> — {escape(description)}")
    return result


def achievements_unlocked(granted: Granted, label: str) -> str:
    return "\n".join(
        [f"<b>{escape(pick(UNLOCKED))}</b> · {who(label)}", "", *achievement_lines(granted.codes)]
    )


# ── panel screens ──────────────────────────────────────────────────────


def home(totals: dict[str, int], chat_id: int) -> str:
    return (
        f"<b>🎛 {escape(pick(ui.MENU_HEADERS, chat_id))}</b>\n\n"
        f"📦 Живых пикч: <b>{totals['alive']}</b>\n"
        f"⚰️ На кладбище: <b>{totals['executed']}</b>\n"
        f"👀 Показов: <b>{totals['shows']}</b> · 🤙🏻 {totals['likes']} · 🖕🏻 {totals['dislikes']}"
    )


def hall(pics: list[Pic], labels: list[str], record: int) -> str:
    lines = ["<b>🏛 Зал славы</b>", "<i>Топ по рейтингу. Кнопки внизу покажут пикчу</i>", ""]
    if not pics:
        lines.append("Пока пусто. Устройте пару дуэлей, тут появятся герои")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        streak = f" · 🔥{pic.best_streak}" if pic.best_streak else ""
        lines.append(
            f"{index}. ⭐ <b>{rating(pic.rating)}</b> · {pic.wins}W/{pic.losses}L{streak} · {who(label)}"
        )
    if record:
        lines += ["", f"🔥 Рекорд серии в чате: <b>{record}</b>"]
    return "\n".join(lines)


def bottom(pics: list[Pic], labels: list[str]) -> str:
    lines = ["<b>🕳 Дно склада</b>", "<i>Худшие по рейтингу. ⚖️ — отправить под суд</i>", ""]
    if not pics:
        lines.append("Дно пустое. Подозрительно")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        lines.append(
            f"{index}. ⭐ <b>{rating(pic.rating)}</b> · {pic.wins}W/{pic.losses}L · 🖕🏻 {pic.dislikes} · {who(label)}"
        )
    return "\n".join(lines)


REMOVAL_REASONS = {"duel": "пала на арене", "court": "казнена судом", "admin": "удалена админом"}


def graveyard(total: int, pics: list[Pic], labels: list[str]) -> str:
    lines = ["<b>⚰️ Кладбище склада</b>", f"Покоится с миром: <b>{total}</b>", ""]
    if not pics:
        lines.append("Пока никто не умер. Скукота")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        reason = REMOVAL_REASONS.get(pic.removed_reason or "", "умерла")
        lines.append(f"{index}. 🪦 {reason} · ⭐ {rating(pic.rating)} · {who(label)}")
    return "\n".join(lines)


def top(board: str, rows: list[tuple[str, int]]) -> str:
    lines = [f"<b>🏆 {escape(top_texts.BOARD_TITLES[board])}</b>", ""]
    if not rows:
        lines.append(escape(pick(top_texts.BOARD_EMPTY)))
        return "\n".join(lines)
    medals = ["🥇", "🥈", "🥉"]
    unit = top_texts.BOARD_UNITS[board]
    for index, (label, value) in enumerate(rows):
        prefix = medals[index] if index < 3 else f"{index + 1}."
        if index == 0:
            roast = pick(top_texts.FIRST_PLACE, board)
        elif index < 3:
            roast = pick(top_texts.PODIUM, board)
        elif index == len(rows) - 1:
            roast = pick(top_texts.LAST_PLACE, board)
        else:
            roast = pick(top_texts.MIDDLE, board)
        lines.append(f"{prefix} {who(label)} — <b>{value}</b> {unit}\n    <i>{escape(roast)}</i>")
    return "\n".join(lines)


def profile(label: str, stats: UserStats, owned: set[str]) -> str:
    title_code = rules.upload_title_code(stats.uploads)
    title = ACHIEVEMENTS[title_code][0] if title_code else "🥚 Никто"
    goal = rules.next_upload_goal(stats.uploads)
    lines = [
        f"<b>👤 {who(label)}</b>",
        f"Титул: <b>{escape(title)}</b>",
        "",
        f"📥 Загружено: <b>{stats.uploads}</b> (живых {stats.pics_alive})",
        f"🤙🏻 Лайков на твоих: <b>{stats.likes_received}</b> · 🖕🏻 {stats.dislikes_received}",
        f"⚰️ Казнено твоих: <b>{stats.pics_executed}</b>",
        f"🔥 Лучшая серия твоей пикчи: <b>{stats.best_streak}</b>",
        f"🏛 В зале славы: <b>{stats.legends}</b>",
        f"🪓 Казнить: {stats.kill_votes} · 🕊 Помиловать: {stats.spare_votes}",
        "",
        f"🏅 Ачивки: <b>{len(owned)}</b> из {len(rules.RULES)}",
    ]
    if goal:
        name = ACHIEVEMENTS[goal.code][0]
        lines.append(f"🎯 До «{escape(name)}»: ещё {goal.threshold - stats.uploads}")
    lines += ["", f"<i>{escape(pick(top_texts.PROFILE_ROASTS))}</i>"]
    return "\n".join(lines)


def upload_hub(is_private: bool) -> str:
    if is_private:
        return "<b>📥 Загрузка</b>\n\nЖми кнопку и кидай фото, альбомы, пересылки. Дубли бот выкинет сам."
    return ui.UPLOAD_PRIVATE_ONLY


def upload_progress(intro: str, added: int, duplicates: int, failed: int) -> str:
    return (
        f"<b>📥 Загрузка</b>\n{escape(intro)}\n\n"
        f"✅ Добавлено: <b>{added}</b>\n"
        f"♻️ Дубли: <b>{duplicates}</b>\n"
        f"⚠️ Не взял: <b>{failed}</b>"
    )


def admin(totals: dict[str, int], users: int, database: str) -> str:
    return (
        "<b>⚙️ Админка</b>\n\n"
        f"📦 Живых: {totals['alive']} · ⚰️ Казнено: {totals['executed']}\n"
        f"👥 Юзеров: {users}\n"
        f"🗄 База: <code>{escape(database)}</code>"
    )
