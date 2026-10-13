"""Message texts for cards and screens. Pure formatting, no I/O.

Visual language:
- header: emoji + bold caps title, then one italic line of flavour or explanation;
- the body is split into blocks by empty lines, a block of 2+ lines opens with a bold label;
- one fact per line, the number in bold first, few emoji (an emoji per word turns into noise);
- a blockquote is always followed by an empty line (Telegram glues the next line to it);
- vote counts first and short emoji bars after them so numbers line up;
- names without "@" (an @mention pings the person every time).
"""

from html import escape

from dataclasses import dataclass

from bot.core import achievements as rules
from bot.core import casino, economy, shop
from bot.core.arena import DEATH_LOSS_STREAK
from bot.db.repo import Battle, Court, Pic, UserStats
from bot.game import BattleReport, CourtReport, Granted
from bot.texts import arena as arena_texts
from bot.texts import captions, court as court_texts, tops as top_texts, ui
from bot.texts import events as event_texts
from bot.texts import games as game_texts
from bot.core import games as game_rules
from bot.texts.achievements import ACHIEVEMENTS, LEVEL_UP, RARITY_MARKS, UNLOCKED
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
    """Flavour line: italic plus an empty line after it. Not a blockquote: a header with a quote
    right under it reads as one glued block in Telegram."""
    return f"<i>{escape(text)}</i>\n"


def cited(text: str) -> str:
    """Words of a person (last word in court): a real blockquote, then an empty line."""
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


def pic_footer(pic: Pic, uploader: str | None, bounty: int = 0) -> str:
    parts = [f"{shop.stage(pic.wins).emoji} ⭐ {rating(pic.rating)}"]
    if pic.wins or pic.losses:
        parts.append(f"⚔️ {pic.wins}–{pic.losses}")
    if uploader:
        parts.append(f"📥 {who(uploader)}")
    if bounty:
        parts.append(f"🎯 {bounty}")
    return f"<i>{' · '.join(parts)}</i>"


def pic_caption(pic: Pic, bucket: str, chat_id: int, uploader: str | None, bounty: int = 0) -> str:
    pool = {"fresh": captions.FRESH, "legend": captions.LEGEND}.get(bucket, captions.CAPTIONS)
    return f"{escape(pick(pool, chat_id))}\n\n{pic_footer(pic, uploader, bounty)}"


# ── battles ────────────────────────────────────────────────────────────


def vote_lines(counts: list[int], labels: tuple[str, ...]) -> list[str]:
    leader = max(counts) if counts else 0
    return [
        f"{labels[slot]} <b>{count}</b>{bar(count, leader, SLOT_COLORS[slot])}"
        for slot, count in enumerate(counts)
    ]


def bets_line(battle: Battle) -> str | None:
    pool = battle.bet_pool()
    total = sum(pool)
    if not total:
        return None
    labels = DUEL_LABELS if battle.kind == "duel" else TOURNAMENT_LABELS
    parts = [f"{labels[slot]} ×{value:g}" for slot, value in enumerate(casino.odds(pool)) if value]
    return f"💰 Ставки: банк <b>{total}</b> · " + " · ".join(parts)


def battle_card(battle: Battle, remaining: int, fighters: str | None = None, flipped: bool = False) -> str:
    """fighters: the 'A vs B, stake' line of a player challenge."""
    counts = battle.vote_counts()
    total = sum(counts)
    is_duel = battle.kind == "duel"
    labels = DUEL_LABELS if is_duel else TOURNAMENT_LABELS
    if battle.mode == "challenge":
        head = "🤺 <b>ВЫЗОВ</b>"
    else:
        head = "⚔️ <b>ДУЭЛЬ</b>" if is_duel else "🏟 <b>ТУРНИР ЧЕТЫРЁХ</b>"
    status_pool = arena_texts.DUEL_STATUS if is_duel else arena_texts.TOURNAMENT_STATUS
    lines = [f"{head} · ⏳ <b>{timer(remaining)}</b>"]
    if battle.title:
        lines.append(f"<i>{escape(battle.title)}</i>")
    lines.append("")
    if fighters:
        lines += [fighters, ""]
    if is_duel and battle.streak > 0:
        lines.append(f"👑 {labels[0]} — чемпионка, серия <b>{battle.streak}</b>")
    marks = [shop.stage(pic.wins).emoji for pic in battle.pics]
    lines += [f"{line}  {mark}" if mark != "🥚" else line for line, mark in zip(vote_lines(counts, labels), marks)]
    lines.append("")
    if flipped:
        lines.append("🙃 <b>Перевёртыш:</b> победит пикча, у которой МЕНЬШЕ голосов")
    bets = bets_line(battle)
    lines.append(bets or f"💰 Ставок нет · кнопка 💰 — ставка {casino.BET_STEP} 🪙 на пикчу")
    if battle.extended and not total:
        lines.append(f"<b>{escape(pick(event_texts.EXTENDED, battle.chat_id))}</b>")
    elif battle.mode == "challenge":
        lines.append("<i>Голосуют только зрители</i>")
    else:
        lines.append(f"<i>{escape(pick(status_pool, battle.chat_id))}</i>")
    return "\n".join(lines)


def battle_result(
    report: BattleReport,
    uploaders: list[str],
    guessers: list[str] | None = None,
    extras: list[str] | None = None,
) -> str:
    """One line per pic, best first: marker, slot, uploader, rating change. `extras` — blocks
    of v4 lines (bets, bounty, evolution, challenge pot) shown after the table."""
    battle = report.battle
    is_duel = battle.kind == "duel"
    labels = DUEL_LABELS if is_duel else TOURNAMENT_LABELS
    if battle.mode == "challenge":
        title = "🤺 <b>ИТОГ ВЫЗОВА</b>"
    else:
        title = "⚔️ <b>ИТОГ ДУЭЛИ</b>" if is_duel else "🏟 <b>ИТОГ ТУРНИРА</b>"

    if not report.counted:
        tail = "\n".join(extras or [])
        return f"{title}\n\n{quote(pick(arena_texts.NOBODY_VOTED, battle.chat_id))}{tail}".rstrip()

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
    if guessers:
        reward = report.guess_reward or economy.GUESS + economy.VOTE
        lines.append(f"🪙 Угадали: {', '.join(who(name) for name in guessers)} <i>(+{reward})</i>")
    if report.flipped:
        lines.append("🙃 <i>Перевёртыш: победила пикча с меньшим числом голосов</i>")
    for block in extras or []:
        lines += ["", block] if block else []
    lines.append("")

    if battle.mode == "challenge":
        from bot.texts.social import CHALLENGE_WIN  # local: only challenges speak this voice

        lines.append(quote(pick(CHALLENGE_WIN if report.winner is not None else arena_texts.DUEL_DRAW, battle.chat_id)))
    elif is_duel:
        pool = arena_texts.DUEL_DRAW if report.winner is None else arena_texts.DUEL_WIN
        lines.append(quote(pick(pool, battle.chat_id)))
        if report.winner is not None and report.streak > 1:
            lines.append(f"🔥 Серия чемпионки: <b>{report.streak}</b>")
        if report.executed:
            lines.append(f"⚰️ <b>{escape(pick(arena_texts.DUEL_EXECUTION, battle.chat_id))}</b>")
            lines.append(
                f"<i>Рейтинг ниже {report.death_rating:.0f} или {DEATH_LOSS_STREAK}-е поражение подряд — арена не прощает</i>"
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
    head = "📜 <b>АПЕЛЛЯЦИЯ</b>" if trial.appeal else "⚖️ <b>НАРОДНЫЙ СУД</b>"
    lines = [
        f"{head} · ⏳ <b>{timer(remaining)}</b>",
        quote(trial.title),
        f"🪓 <b>{kill}</b>{bar(kill, leader, '🟥')}",
        f"🕊 <b>{spare}</b>{bar(spare, leader, '🟩')}",
        "",
        f"<i>{escape(pick(court_texts.STATUS, trial.chat_id))}</i>",
    ]
    if trial.appeal:
        lines.append("<i>Повторный суд: для казни нужно 3 голоса 🪓 и большинство</i>")
    if trial.last_word:
        lines += [
            "",
            f"🗣 <b>{escape(pick(court_texts.LAST_WORD_INTRO, trial.chat_id))}</b>",
            cited(trial.last_word),
        ]
    else:
        lines += ["", f"🗣 <i>{who(uploader)}, ответь на это сообщение — это будет последнее слово</i>"]
    return "\n".join(lines)


def court_result(report: CourtReport, uploader: str, extras: list[str] | None = None) -> str:
    trial = report.court
    kill, spare = trial.vote_counts()
    executed = report.verdict == "executed"
    head = "⚰️ <b>ПРИГОВОР: КАЗНЕНА</b>" if executed else "🕊 <b>ПРИГОВОР: ПОМИЛОВАНА</b>"
    if trial.appeal:
        head += " <i>· окончательно</i>" if executed else " <i>· по апелляции</i>"
    pool = court_texts.EXECUTED if executed else court_texts.PARDONED
    lines = [head, f"🪓 <b>{kill}</b> · 🕊 <b>{spare}</b>", "", quote(pick(pool, trial.chat_id))]
    if report.amnesty:
        lines.append("🕊 <b>Амнистия:</b> сегодня суд никого не казнит")
    if trial.last_word:
        lines.append(f"<i>Последнее слово: «{escape(trial.last_word)}»</i>")
    if report.bail_back:
        lines.append(f"📜 Залог {report.bail_back} 🪙 вернулся загрузчику")
    lines += extras or []
    lines.append(f"<i>📥 {who(uploader)}" + ("" if executed else " · иммунитет на неделю") + "</i>")
    return "\n".join(lines)


# ── achievements ───────────────────────────────────────────────────────


NOTE_CHESTS = {"wood": "🟫 деревянный сундук", "rare": "🟪 редкий сундук", "legend": "🟨 легендарный сундук"}


def note_line(label: str, note) -> str:
    from bot.texts.progress import quest_name  # local: progress texts are only needed here

    if note.kind == "quest":
        name = quest_name(note.code, note.target)
        return f"📜 <b>{who(label)}</b> — квест «{escape(name)}» · +{note.amount} 🪙"
    if note.kind == "quests_all":
        return f"📋 Все квесты дня закрыты: <b>{who(label)}</b> · +{note.amount} 🪙 и {NOTE_CHESTS['wood']}"
    if note.kind == "challenge":
        name = quest_name(note.code, note.target)
        return f"🏆 <b>{who(label)}</b> — челлендж недели «{escape(name)}» · +{note.amount} 🪙 и {NOTE_CHESTS['rare']}"
    if note.kind == "challenges_all":
        return f"💎 <b>{who(label)}</b> — все челленджи недели! Держи {NOTE_CHESTS['legend']}"
    return f"🎁 <b>{who(label)}</b> находит {NOTE_CHESTS.get(note.code, 'сундук')}"


def announcement(items: list[tuple[str, Granted]]) -> str:
    """All achievements, level-ups, quests and chests of one event in a single message; the same
    achievement for several people becomes one line."""
    if not any(granted.codes or granted.level_up for _, granted in items):
        return "\n".join(note_line(label, note) for label, granted in items for note in granted.notes)
    lines = [f"<b>{escape(pick(UNLOCKED))}</b>"]
    for label, granted in items:
        if granted.level_up:
            lines.append(f"\n⬆️ <b>{who(label)}</b> → {escape(granted.level_up)}\n<i>{escape(pick(LEVEL_UP))}</i>")
    by_code: dict[str, list[str]] = {}
    for label, granted in items:
        for code in granted.codes:
            by_code.setdefault(code, []).append(label)
    ordered = sorted(by_code, key=lambda code: (rules.RARITY_ORDER[rules.rarity(code)], code))
    for code in ordered:
        name, description = ACHIEVEMENTS.get(code, (code, ""))
        mark = RARITY_MARKS[rules.rarity(code)]
        people = ", ".join(who(label) for label in by_code[code])
        lines.append(f"\n{mark}<b>{escape(name)}</b> — {people}\n<i>{escape(description)}</i>")
    notes = [note_line(label, note) for label, granted in items for note in granted.notes]
    if notes:
        lines += ["", *notes]
    return "\n".join(lines)


def has_legendary(granted: list[Granted]) -> bool:
    return any(rules.rarity(code) == rules.LEGENDARY for item in granted for code in item.codes)


# ── panel screens ──────────────────────────────────────────────────────


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
        f"👀 <b>{totals['shows']}</b> {plural(totals['shows'], 'показ', 'показа', 'показов')}"
        f" · 🤙🏻 {totals['likes']} · 🖕🏻 {totals['dislikes']}",
    ]
    if live_now:
        lines += ["", "🔴 <b>Сейчас идёт</b>", *live_now]
    return "\n".join(lines)


def hall(pics: list[Pic], labels: list[str], record: int) -> str:
    lines = ["🏛 <b>ЗАЛ СЛАВЫ</b>", "<i>Рейтинг · автор · победы–поражения. 👀 — показать</i>", ""]
    if not pics:
        lines.append("Пока пусто. Устройте пару дуэлей — тут появятся герои")
    for index, (pic, label) in enumerate(zip(pics, labels)):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        streak = f" · 🔥{pic.best_streak}" if pic.best_streak > 1 else ""
        lines.append(f"{place} <b>{rating(pic.rating)}</b>  {who(label)}  <i>{pic.wins}–{pic.losses}{streak}</i>")
    if record:
        lines += ["", f"<i>👑 Рекорд серии в чате: {record}</i>"]
    return "\n".join(lines)


def bottom(pics: list[Pic], labels: list[str]) -> str:
    lines = ["🕳 <b>ДНО СКЛАДА</b>", "<i>Рейтинг · автор · 🖕🏻. ⚖️ — отправить под суд</i>", ""]
    if not pics:
        lines.append("Дно пустое. Подозрительно")
    for index, (pic, label) in enumerate(zip(pics, labels), start=1):
        lines.append(f"{index}. <b>{rating(pic.rating)}</b>  {who(label)}  <i>🖕🏻 {pic.dislikes}</i>")
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
    lines = [f"<b>{escape(title).upper()}</b>", f"<i>{escape(subtitle.capitalize())}</i>", ""]
    if not rows:
        lines.append(escape(pick(top_texts.BOARD_EMPTY)))
        return "\n".join(lines)
    for index, (label, value) in enumerate(rows):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        unit = plural(value, "пикча", "пикчи", "пикч") if board == "uploads" else top_texts.BOARD_UNITS[board]
        lines.append(f"{place} {who(label)} — <b>{value}</b> {unit}")
    lines += ["", f"<i>🥇 {who(rows[0][0])}: {escape(pick(top_texts.FIRST_PLACE, board))}</i>"]
    if len(rows) > 3:
        lines.append(f"<i>🐌 {who(rows[-1][0])}: {escape(pick(top_texts.LAST_PLACE, board))}</i>")
    elif len(rows) > 1:
        lines.append(f"<i>🥈 {who(rows[1][0])}: {escape(pick(top_texts.PODIUM, board))}</i>")
    return "\n".join(lines)


@dataclass(frozen=True)
class Wallet:
    coins: int
    earned: int
    streak: int  # days in a row with any vote or reaction
    right_guesses: int = 0
    wrong_guesses: int = 0
    nemesis: tuple[str, int] | None = None  # (name, defeats)
    crowns: tuple[str, ...] = ()
    spouse: tuple[str, int] | None = None  # (name, days)
    title: str | None = None
    chests: dict[str, int] | None = None
    jailed: int = 0  # seconds left


def profile(
    label: str,
    stats: UserStats,
    owned: set[str],
    place: int | None,
    wallet: Wallet,
    owners: dict[str, int],
    players: int,
) -> str:
    level = economy.level_for(wallet.earned)
    upcoming = economy.next_level(wallet.earned)
    lines = [f"👤 <b>{who(label).upper()}</b>"]
    if wallet.title:
        lines.append(f"🏷 «{escape(wallet.title)}»")
    lines += [f"<i>{escape(level.name)} · уровень {level.index + 1} из {len(economy.LEVELS)}</i>", ""]
    if upcoming:
        lines += [
            f"<code>{economy.progress(wallet.earned)}</code>  {wallet.earned} / {upcoming.threshold}",
            f"<i>дальше — {escape(upcoming.name)}</i>",
            "",
        ]
    wealth = f"🪙 <b>{wallet.coins}</b> {plural(wallet.coins, 'коин', 'коина', 'коинов')}"
    if wallet.streak > 1:
        wealth += f" · 🔥 {wallet.streak} {plural(wallet.streak, 'день', 'дня', 'дней')} подряд"
    lines.append(wealth)
    for kind in wallet.crowns:
        badge, crown = economy.CROWNS[kind]
        lines.append(f"{badge} {escape(crown)}")
    if wallet.spouse:
        name, days_married = wallet.spouse
        lines.append(f"💍 В браке с <b>{who(name)}</b> · {days_married} {plural(days_married, 'день', 'дня', 'дней')}")
    owned_chests = [(tier, count) for tier, count in (wallet.chests or {}).items() if count]
    if owned_chests:
        marks = {"wood": "🟫", "rare": "🟪", "legend": "🟨"}
        lines.append("🎒 Сундуки: " + " · ".join(f"{marks[tier]} {count}" for tier, count in owned_chests))
    if wallet.jailed:
        lines.append(f"🚔 В обезьяннике ещё {wallet.jailed // 60 + 1} мин")

    rank = f" · {place}-е место" if place else ""
    lines += ["", f"📦 <b>Склад</b>{rank}"]
    alive = "все живы" if stats.pics_alive == stats.uploads else f"живых {stats.pics_alive}"
    lines.append(
        f"<b>{stats.uploads}</b> {plural(stats.uploads, 'пикча', 'пикчи', 'пикч')} · {alive}"
        + (f" · ⚰️ {stats.pics_executed}" if stats.pics_executed else "")
    )
    lines.append(f"🤙🏻 <b>{stats.likes_received}</b> · 🖕🏻 <b>{stats.dislikes_received}</b> на твоих пикчах")
    if stats.legends or stats.best_streak > 1:
        lines.append(f"🏛 <b>{stats.legends}</b> в зале славы · 🔥 лучшая серия <b>{stats.best_streak}</b>")
    title_code = rules.upload_title_code(stats.uploads)
    goal = rules.next_upload_goal(stats.uploads)
    if title_code and goal:
        left = goal.threshold - stats.uploads
        lines.append(
            f"<i>{escape(ACHIEVEMENTS[title_code][0])} → {escape(ACHIEVEMENTS[goal.code][0])}: "
            f"ещё {left} {plural(left, 'пикча', 'пикчи', 'пикч')}</i>"
        )
    elif title_code:
        lines.append(f"<i>{escape(ACHIEVEMENTS[title_code][0])}</i>")

    voice = economy.people_voice(wallet.right_guesses, wallet.wrong_guesses)
    if voice or wallet.nemesis or stats.kill_votes or stats.spare_votes:
        lines += ["", "⚔️ <b>Арена и суды</b>"]
        if stats.kill_votes or stats.spare_votes:
            lines.append(f"🪓 казнил <b>{stats.kill_votes}</b> · 🕊 спас <b>{stats.spare_votes}</b>")
        if voice:
            lines.append(f"🎯 угадываешь победителя в <b>{voice[0]}%</b> · {escape(voice[1])}")
        if wallet.nemesis:
            name, defeats = wallet.nemesis
            lines.append(
                f"😈 немезида — <b>{who(name)}</b> · {defeats} "
                f"{plural(defeats, 'поражение', 'поражения', 'поражений')} твоих пикч"
            )

    hidden = len(rules.SECRET - owned)
    secret = f" · 🔒 ещё {hidden} {plural(hidden, 'секретная', 'секретные', 'секретных')}" if hidden else ""
    lines += ["", f"🏅 <b>Ачивки</b> · {len(owned)} из {len(rules.ALL_CODES)}{secret}"]
    if owned:
        lines += [escape(ACHIEVEMENTS[code][0]) for code in rules.showcase(owned, owners)]
        listing = ["Вся коллекция · у скольких есть"]
        for tier, heading in ((rules.LEGENDARY, "🌟 Легендарные"), ("rare", "✨ Редкие"), ("common", "▫️ Обычные")):
            codes = sorted(code for code in owned if rules.rarity(code) == tier)
            if codes:
                listing += ["", heading]
                for code in codes:
                    share = round(100 * owners.get(code, 1) / players)
                    listing.append(f"{ACHIEVEMENTS[code][0]} · {share}%")
        lines.append(f"<blockquote expandable>{escape(chr(10).join(listing))}</blockquote>\n")
    else:
        lines += ["<i>Пока ни одной. Проголосуй в дуэли — это уже начало</i>", ""]
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
        "<i>Только для админов</i>\n\n"
        f"📦 <b>{totals['alive']}</b> живых · ⚰️ <b>{totals['executed']}</b> казнено\n"
        f"👥 <b>{users}</b> юзеров\n"
        f"🗄 <code>{escape(database)}</code>\n\n"
        "🕒 <b>Расписание</b>\n"
        "04:00 — 💾 бэкап админам\n"
        "12:00 — 🌅 пикча дня\n"
        "19:00 — ⚖️ суд над худшей\n"
        "Вс 18:00 — 📅 итоги недели и короны"
    )


# ── mini-games ─────────────────────────────────────────────────────────


GAMES_SCREEN = (
    "🎮 <b>ИГРЫ</b>\n"
    "<i>Всё, за что капают 🪙 помимо арены. Казино — отдельной кнопкой в пульте</i>\n"
    "\n"
    "👹 <b>Босс</b> · /boss\n"
    "Пикча-чудовище на 10 минут. Чат бьёт его кнопками, добыча делится по урону. "
    "Приходит сам в 16:00, призвать можно раз в 3 часа\n"
    "\n"
    "🖋 <b>Подпиши пикчу</b> · /caption\n"
    f"Минута на подпись ответом на пикчу, потом анонимное голосование. Победителю +{economy.CAPTION_WIN} 🪙\n"
    "\n"
    "🎡 <b>Колесо фортуны</b> · /wheel\n"
    "Раз в день бесплатно: монеты, проклятие или благословение твоей пикчи, легенда. 777 — +100 🪙\n"
    "\n"
    "🔮 <b>Гороскоп</b> · /horoscope\n"
    "Личная пикча и предсказание, раз в день\n"
    "\n"
    "⚡ <b>Золотая пикча</b>\n"
    f"Иногда выпадает в рандоме. Кто первый нажмёт — тому +{economy.GOLD} 🪙"
)


def caption_card(game: dict, remaining: int, chat_id: int) -> str:
    entries = game["entries"]
    if game["phase"] == "collect":
        count = len(entries)
        return (
            f"🖋 <b>ПОДПИШИ ПИКЧУ</b> · ⏳ <b>{timer(remaining)}</b>\n"
            f"{quote(pick(game_texts.CAPTION_START, chat_id))}\n"
            "Ответь на это сообщение своей подписью — до "
            f"{game_rules.CAPTION_MAX_LENGTH} символов, можно переписать.\n"
            f"✍️ Подписей: <b>{count}</b> из {game_rules.CAPTION_MAX_ENTRIES}"
        )
    tally: dict[int, int] = {}
    for author in game["votes"].values():
        tally[author] = tally.get(author, 0) + 1
    lines = [
        f"🗳 <b>ЛУЧШАЯ ПОДПИСЬ?</b> · ⏳ <b>{timer(remaining)}</b>",
        quote(pick(game_texts.CAPTION_VOTE, chat_id)),
    ]
    for index, entry in enumerate(entries, start=1):
        votes = tally.get(entry["user_id"], 0)
        lines.append(f"<b>{index}.</b> {escape(entry['text'])}" + (f"  <i>· {votes}</i>" if votes else ""))
    return "\n".join(lines)


def caption_result(game: dict, labels: dict[int, str], chat_id: int) -> str:
    tally: dict[int, int] = {}
    for author in game["votes"].values():
        tally[author] = tally.get(author, 0) + 1
    winner = game.get("winner")
    head = "🖋 <b>ИТОГИ: ПОДПИШИ ПИКЧУ</b>"
    pool = game_texts.CAPTION_WIN if winner is not None else game_texts.CAPTION_NO_VOTES
    lines = [head, quote(pick(pool, chat_id))]
    ordered = sorted(game["entries"], key=lambda entry: -tally.get(entry["user_id"], 0))
    for entry in ordered:
        mark = "👑" if entry["user_id"] == winner else "▫️"
        votes = tally.get(entry["user_id"], 0)
        lines.append(f"{mark} «{escape(entry['text'])}» — {who(labels.get(entry['user_id'], '?'))} · {votes}")
    if winner is not None:
        lines.append(f"\n🪙 <b>{who(labels.get(winner, '?'))}</b> +{economy.CAPTION_WIN}")
    return "\n".join(lines)


def caption_cancelled(chat_id: int) -> str:
    return f"🖋 <b>ПОДПИШИ ПИКЧУ</b>\n{quote(pick(game_texts.CAPTION_CANCELLED, chat_id))}"


def gold_caption() -> str:
    return (
        f"⚡ <b>ЗОЛОТАЯ ПИКЧА</b>\n{quote(pick(game_texts.GOLD))}"
        f"<i>Кто первый нажмёт «⚡ Забрать» — тому +{economy.GOLD} 🪙 и ачивка</i>"
    )


def spin_result(label: str, spin: game_rules.Spin, pic: Pic | None, balance: int, chat_id: int) -> str:
    lines = [
        f"🎡 <b>КОЛЕСО: {game_texts.SPIN_TITLES[spin.kind].split(' ', 1)[1]}</b> · {who(label)}",
        quote(pick(game_texts.SPIN_RESULTS[spin.kind], chat_id)),
    ]
    if spin.coins:
        sign = "+" if spin.coins > 0 else "−"
        lines.append(f"🪙 {sign}{abs(spin.coins)} · баланс <b>{balance}</b>")
    if spin.kind in ("curse", "bless"):
        if pic is None:
            lines.append("<i>…но твоих пикч на складе нет, так что мимо</i>")
        else:
            delta = -shop.CURSE_RATING if spin.kind == "curse" else game_rules.BLESS_RATING
            sign = "+" if delta > 0 else "−"
            lines.append(f"⭐ Случайная твоя пикча: {sign}{abs(delta)} рейтинга (теперь {rating(pic.rating + delta)})")
            if spin.kind == "curse":
                lines.append("<i>🧿 Порчу можно снять за сутки: кнопка 🛒 под пикчей</i>")
    return "\n".join(lines)


def horoscope(label: str, chat_id: int) -> str:
    return f"🔮 <b>ГОРОСКОП · {who(label).upper()}</b>\n{quote(pick(game_texts.HOROSCOPE, chat_id))}".rstrip()
