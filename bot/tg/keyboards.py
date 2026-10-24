"""Inline keyboards. callback_data must stay ≤ 64 bytes.

Scheme:
  m:<screen>[:arg]      live panel navigation
  pic                   draw a pic
  r:<+|->:<pic>         reaction
  d:new | d:ch:<battle> duel / champion continues
  t:new                 tournament
  v:<battle>:<slot>     battle vote
  c:<k|s>:<court>       court vote
  c:go:<pic>            summon a pic from the bottom
  show:<pic>            send a hall-of-fame pic
  trial                 "court in progress" placeholder
  up:<start|done|cancel>
  adm:<health|backup|reset|reset!|spare:<pic>>
  bt:<battle>:<slot>    arena bet
  cg:<game> | cs:<amount|all> | cp:<game>:<stake>   casino: play / set stake / play at stake
  pm:<pic>              pic shop menu;  sh:<item>:<pic>:<uid>  buy for a pic
  res:<pic>             resurrect from the graveyard;  title  buy a title
  ap:<court>            appeal
  daily | ch:<tier>     daily bonus / open a chest
  bh:<boss> | bs:<boss> boss hit / super hit;  boss  summon
  mr:<y|n>:<proposal>   marriage answer;  cl:<y|n>:<challenge>  challenge answer
  ak:<chat>:<user>:<n|x>  answer to "whom? / how much? / sure?" for /rob /give /marry /pvp /challenge /divorce
  pp:<action>           start one of those from the «👥 Люди» panel screen
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.texts.ui import BACK

PRIMARY = "primary"
SUCCESS = "success"
DANGER = "danger"
DUEL_LABELS = ("🅰️", "🅱️")
# Vote buttons match the collage badges: red, blue, green, then the app default for yellow.
SLOT_STYLES = (DANGER, PRIMARY, SUCCESS, None)
TOURNAMENT_LABELS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")
TOP_BOARDS = (
    ("uploads", "📥 Загрузки"),
    ("loved", "❤️ Любимцы"),
    ("killers", "🪓 Палачи"),
    ("streaks", "🔥 Серии"),
    ("rich", "💰 Богачи"),
    ("season", "📅 Сезон"),
    ("hl", "🎯 Выше-ниже"),
)
WEEKLY_BOARDS = {"uploads", "loved", "killers", "rich"}
# Telegram truncates long labels on phones: keep ≤ 8 chars with 3 buttons in a row, ≤ 12 with 2.


def short(amount: int) -> str:
    """Prices on buttons: 1 500 → 1.5к, 2 000 000 → 2М. Labels have to stay short on phones."""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}".rstrip("0").rstrip(".") + "М"
    if amount >= 10_000:
        return f"{amount // 1000}к"
    if amount >= 1000:
        return f"{amount / 1000:.1f}".rstrip("0").rstrip(".") + "к"
    return str(amount)


def button(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    if style:
        return InlineKeyboardButton(text=text, callback_data=data, style=style)
    return InlineKeyboardButton(text=text, callback_data=data)


def link(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def markup(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def back(to: str = "m:home") -> list[InlineKeyboardButton]:
    return [button(BACK, to)]


def more() -> InlineKeyboardButton:
    """«🎲 Ещё»: under almost every card, the one way to keep the chat going."""
    return button("🎲 Ещё", "pic", PRIMARY)


def numbered(pic_ids: list[str], label: str, data: str, style: str | None = None) -> list[list[InlineKeyboardButton]]:
    """«👀 1 … 👀 10» in rows of five."""
    buttons = [button(f"{label} {index}", f"{data}:{pic_id}", style) for index, pic_id in enumerate(pic_ids, start=1)]
    return [buttons[start : start + 5] for start in range(0, len(buttons), 5)]


def home(is_admin: bool) -> InlineKeyboardMarkup:
    return markup(
        [button("🎲 Пикчу", "pic", PRIMARY), button("⚔️ Дуэль", "d:new", PRIMARY)],
        [button("🏟 Турнир", "t:new", PRIMARY), button("🎮 Игры", "m:games", PRIMARY)],
        [button("👥 Люди", "m:people", PRIMARY), button("🎰 Казино", "m:casino", SUCCESS)],
        [button("🛒 Лавка", "m:shop", SUCCESS), button("🎁 Бонус", "daily", SUCCESS)],
        [button("📜 Квесты", "m:quests"), button("🏆 Рейтинги", "m:top:uploads")],
        [button("👤 Я", "m:me"), button("📥 Загрузить", "m:up")],
        [button("❓ Правила", "m:help"), button("🔄 Обновить", "m:home:refresh")],
        [button("⚙️ Админка", "m:adm")] if is_admin else [],
    )


def games_menu() -> InlineKeyboardMarkup:
    return markup(
        [button("🕵️ Чья пикча", "gm:whose", PRIMARY), button("🎯 Выше-ниже", "gm:hl", PRIMARY)],
        [button("🖋 Подпиши", "gm:caption", PRIMARY), button("👹 Босс", "boss", DANGER)],
        [button("🎡 Колесо", "gm:spin", SUCCESS), button("🔮 Гороскоп", "gm:horo")],
        back(),
    )


def people_menu() -> InlineKeyboardMarkup:
    """Each button starts the action; whom and how much the bot then asks personally."""
    return markup(
        [button("😈 Ограбить", "pp:rob", DANGER), button("🎁 Подарить", "pp:give", SUCCESS)],
        [button("🤺 Вызов", "pp:challenge", PRIMARY), button("🎲 1 на 1", "pp:pvp", PRIMARY)],
        [button("💍 Свадьба", "pp:marry"), button("💔 Развод", "pp:divorce")],
        back(),
    )


# ── v4 ─────────────────────────────────────────────────────────────────

CASINO_BUTTONS = (
    ("slots", "🎰 Слоты"),
    ("dice", "🎲 Кости"),
    ("darts", "🎯 Дартс"),
    ("basket", "🏀 Баскет"),
    ("football", "⚽ Футбол"),
    ("bowling", "🎳 Кегли"),
)


def casino_menu(shares: tuple[int, ...], current: str = "") -> InlineKeyboardMarkup:
    """current: the active stake button's data ('p10', 'all'), marked with ✅."""
    games = [button(label, f"cg:{code}", SUCCESS if code == "slots" else None) for code, label in CASINO_BUTTONS]

    def stake(label: str, data: str, style: str | None = None) -> InlineKeyboardButton:
        return button(f"✅ {label}" if data == current else label, f"cs:{data}", style)

    stakes = [stake(f"{share}%", f"p{share}") for share in shares]
    return markup(games[:3], games[3:], stakes, [stake("🃏 Ва-банк", "all", DANGER)], back())


def casino_again(game: str, stake: int) -> InlineKeyboardMarkup:
    half = max(10, stake // 2)
    return markup(
        [
            button(f"🔁 {stake}", f"cp:{game}:{stake}", SUCCESS),
            button(f"⏫ {stake * 2}", f"cp:{game}:{stake * 2}"),
            button(f"⏬ {half}", f"cp:{game}:{half}"),
        ]
    )


def pic_menu(token: str, cursed: bool, prices: dict[str, int], bounties: tuple[int, int] = (100, 500)) -> InlineKeyboardMarkup:
    """token: a short server-side key for (pic, buyer, chat) — see shop.menu_token."""

    def buy(label: str, item: str, code: str, style: str | None = None) -> InlineKeyboardButton:
        return button(f"{label} {short(prices[item])}", f"sh:{code}:{token}", style)

    rows = [
        [buy("🛡 Щит", "shield", "s", SUCCESS), buy("⚡ Буст", "boost", "b", PRIMARY)],
        [buy("⚖️ Суд", "court", "c", DANGER), button(f"🎯 +{short(bounties[0])}", f"sh:h1:{token}")],
        [button(f"🎯 +{short(bounties[1])}", f"sh:h5:{token}")],
    ]
    if cursed:
        rows[2].append(buy("🧿 Порча", "uncurse", "u", SUCCESS))
    return markup(*rows)


def shop_menu() -> InlineKeyboardMarkup:
    return markup([button("🏷 Купить титул", "title", PRIMARY)], [button("⚰️ Кладбище", "m:grave"), *back()])


def appeal(court_id: str) -> InlineKeyboardMarkup:
    return markup([button("📜 Апелляция", f"ap:{court_id}", PRIMARY), more()])


def quests_menu(daily_ready: bool, chests: dict[str, int], chat_id: int | None = None) -> InlineKeyboardMarkup:
    """chat_id goes into the buttons when the screen is ephemeral: such callbacks may come
    without the message, and the bot still has to know where to post."""
    suffix = f":{chat_id}" if chat_id is not None else ""
    rows = []
    if daily_ready:
        rows.append([button("🎁 Забрать бонус", f"daily{suffix}", SUCCESS)])
    rows.append(chest_buttons(chests, suffix))
    if chat_id is None:
        rows.append(back())
    return markup(*rows)


CHEST_LABELS = {"wood": "🟫 Сундук", "rare": "🟪 Сундук", "legend": "🟨 Сундук"}  # tap = open one


def chest_buttons(chests: dict[str, int], suffix: str = "") -> list[InlineKeyboardButton]:
    return [button(CHEST_LABELS[tier], f"ch:{tier}{suffix}", SUCCESS) for tier, count in chests.items() if count]


def open_chests(tiers: list[str], chat_id: int | None = None) -> InlineKeyboardMarkup | None:
    """chat_id goes into the buttons of a personal (ephemeral) message: its callbacks may come
    without the message."""
    if not tiers:
        return None
    suffix = f":{chat_id}" if chat_id is not None else ""
    return markup([button(CHEST_LABELS[tier], f"ch:{tier}{suffix}", SUCCESS) for tier in dict.fromkeys(tiers)])


def boss(boss_id: str, price: int) -> InlineKeyboardMarkup:
    return markup([button("🗡 Удар", f"bh:{boss_id}", DANGER), button(f"🔥 Супер {short(price)}", f"bs:{boss_id}", PRIMARY)])


def season_over() -> InlineKeyboardMarkup:
    return markup([button("🏆 Сезоны", "m:seasons", PRIMARY), button("🎰 Казино", "m:casino", SUCCESS)])


def boss_over() -> InlineKeyboardMarkup:
    return markup([more(), button("🎮 Игры", "m:games")])


def proposal(proposal_id: str) -> InlineKeyboardMarkup:
    return markup([button("💍 Да", f"mr:y:{proposal_id}", SUCCESS), button("💔 Нет", f"mr:n:{proposal_id}", DANGER)])


def fit(name: str, limit: int = 14) -> str:
    """A name on a half-width button: whole if it fits, else the first name, else cut with «…»."""
    if len(name) <= limit:
        return name
    first = name.split()[0]
    return first if len(first) <= limit else name[: limit - 1] + "…"


def ask(chat_id: int, owner: int, labels: list[str]) -> InlineKeyboardMarkup:
    """People or amounts to pick from, two a row, and a way out. Only `owner` may press."""
    buttons = [button(fit(label), f"ak:{chat_id}:{owner}:{index}", PRIMARY) for index, label in enumerate(labels)]
    rows = [buttons[start : start + 2] for start in range(0, len(buttons), 2)]
    return markup(*rows, [button("✖️ Отмена", f"ak:{chat_id}:{owner}:x")])


def challenge(challenge_id: str) -> InlineKeyboardMarkup:
    return markup(
        [button("✅ Принять", f"cl:y:{challenge_id}", SUCCESS), button("❌ Отказ", f"cl:n:{challenge_id}", DANGER)]
    )


def rematch(challenge_id: str, stake: int, dice: bool) -> InlineKeyboardMarkup:
    second = button("🎰 Казино", "m:casino", SUCCESS) if dice else more()
    return markup([button(f"🔁 Реванш {short(stake)}", f"rm:{challenge_id}", DANGER), second])


def caption_vote(game_id: str, entries: int) -> InlineKeyboardMarkup:
    buttons = [button(f"{index + 1}", f"cv:{game_id}:{index}", PRIMARY) for index in range(entries)]
    return markup(buttons[:4], buttons[4:])


def clip(label: str, limit: int = 11) -> str:
    return label if len(label) <= limit else label[: limit - 1] + "…"


def whose(game_id: str, labels: list[str]) -> InlineKeyboardMarkup:
    buttons = [button(clip(label), f"wh:{game_id}:{index}", PRIMARY) for index, label in enumerate(labels)]
    return markup(buttons[:2], buttons[2:])


def after_whose() -> InlineKeyboardMarkup:
    return markup([button("🕵️ Ещё раунд", "gm:whose", PRIMARY), more()])


def higher_lower(token: str) -> InlineKeyboardMarkup:
    return markup([button("🅰️ Выше", f"hl:0:{token}", DANGER), button("🅱️ Выше", f"hl:1:{token}", PRIMARY)])


def higher_lower_over() -> InlineKeyboardMarkup:
    return markup([button("🔁 Ещё раз", "hl:new", SUCCESS), button("🏆 Рекорды", "m:top:hl")])


def higher_lower_link(username: str) -> InlineKeyboardMarkup:
    return markup([link("🎯 Играть в личке", f"https://t.me/{username}?start=hl")])


def after_caption() -> InlineKeyboardMarkup:
    return markup([button("🖋 Ещё пикчу", "gm:caption", PRIMARY)])


def gold(token: str) -> InlineKeyboardMarkup:
    return markup([button("⚡ Забрать", f"gold:{token}", SUCCESS)])


def gold_taken(label: str) -> InlineKeyboardMarkup:
    return markup([button(f"🏆 {fit(label, 10)}", "gold:taken"), more()])


def after_wheel() -> InlineKeyboardMarkup:
    return markup([button("🎰 В казино", "m:casino", SUCCESS), more()])


def pic_actions(pic_id: str, likes: int, dislikes: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(f"🤙🏻 {likes}", f"r:+:{pic_id}", SUCCESS),
            button(f"🖕🏻 {dislikes}", f"r:-:{pic_id}", DANGER),
            button("🛒", f"pm:{pic_id}"),
            more(),
        ]
    )


def on_trial() -> InlineKeyboardMarkup:
    return markup([button("⚖️ Идёт суд", "trial", DANGER), more()])


def more_only() -> InlineKeyboardMarkup:
    return markup([more()])


def battle_vote(battle_id: str, kind: str, counts: list[int], step: int = 50) -> InlineKeyboardMarkup:
    labels = DUEL_LABELS if kind == "duel" else TOURNAMENT_LABELS
    buttons = [
        button(f"{labels[slot]} {count}", f"v:{battle_id}:{slot}", SLOT_STYLES[slot])
        for slot, count in enumerate(counts)
    ]
    stake = f"+{short(step)}" if len(counts) == 2 else ""
    bets = [button(f"💰 {labels[slot]} {stake}".rstrip(), f"bt:{battle_id}:{slot}") for slot in range(len(counts))]
    return markup(buttons, bets)


def after_duel(battle_id: str, has_champion: bool) -> InlineKeyboardMarkup:
    rows = [[button("⚔️ Новая дуэль", "d:new", PRIMARY)]]
    if has_champion:
        rows.insert(0, [button("👑 Чемпион дальше", f"d:ch:{battle_id}", SUCCESS)])
    return markup(*rows)


def after_tournament() -> InlineKeyboardMarkup:
    return markup([button("🏟 Ещё турнир", "t:new", PRIMARY)])


def court_vote(court_id: str, kill: int, spare: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(f"🪓 Казнь {kill}", f"c:k:{court_id}", DANGER),
            button(f"🕊 Жить {spare}", f"c:s:{court_id}", SUCCESS),
        ]
    )


def hall(pic_ids: list[str]) -> InlineKeyboardMarkup:
    return markup(*numbered(pic_ids, "👀", "show"), back("m:top:uploads"))


def bottom(pic_ids: list[str]) -> InlineKeyboardMarkup:
    return markup(*numbered(pic_ids, "⚖️", "c:go", DANGER), back("m:top:uploads"))


def graveyard(pic_ids: list[str], is_admin: bool) -> InlineKeyboardMarkup:
    revive = numbered(pic_ids, "🧟", "res")
    spare = numbered(pic_ids, "🕊", "adm:spare", SUCCESS) if is_admin else []
    return markup(*revive, *spare, back("m:top:uploads"))


def tops(active: str, week: bool = False) -> InlineKeyboardMarkup:
    """Board tabs keep the chosen period where the board has a weekly variant."""

    def tab(board: str, label: str) -> InlineKeyboardButton:
        suffix = ":w" if week and board in WEEKLY_BOARDS else ""
        return button(("✅ " + label.split(" ", 1)[1]) if board == active else label, f"m:top:{board}{suffix}")

    tabs = [tab(board, label) for board, label in TOP_BOARDS]
    period = []
    if active in WEEKLY_BOARDS:
        period = [
            button("✅ Неделя" if week else "📆 Неделя", f"m:top:{active}:w"),
            button("♾ Всё время" if week else "✅ Всё время", f"m:top:{active}"),
        ]
    return markup(
        *(tabs[start : start + 2] for start in range(0, len(tabs), 2)),
        period,
        [button("🏛 Зал славы", "m:hall"), button("🕳 Дно", "m:bottom")],
        [button("⚰️ Кладбище", "m:grave"), button("🏆 Сезоны", "m:seasons")],
        back(),
    )


def profile(best_pic: str | None) -> InlineKeyboardMarkup:
    show = [button("⭐ Лучшая пикча", f"show:{best_pic}", PRIMARY)] if best_pic else []
    return markup(show, back())


def upload_hub(is_private: bool) -> InlineKeyboardMarkup:
    if is_private:
        return markup([button("📥 Начать загрузку", "up:start", SUCCESS)], back())
    return markup(back())


def uploading() -> InlineKeyboardMarkup:
    return markup([button("✅ Готово", "up:done", SUCCESS), button("✖️ Отмена", "up:cancel", DANGER)])


def admin(events_on: bool | None = None) -> InlineKeyboardMarkup:
    """events_on is None in private chats, where scheduled events don't apply."""
    events_row = []
    if events_on is not None:
        label = "🔔 События: вкл" if events_on else "🔕 События: выкл"
        events_row = [button(label, "adm:events", SUCCESS if events_on else None)]
    return markup(
        [button("🩺 Состояние", "adm:health"), button("💾 Бэкап", "adm:backup")],
        [button("📊 Статистика", "adm:stats", PRIMARY)],
        events_row,
        [button("🧨 Сбросить статистику", "adm:reset", DANGER)],
        back(),
    )


def admin_reset_confirm() -> InlineKeyboardMarkup:
    return markup(
        [button("💀 Да, всё стереть", "adm:reset!", DANGER)],
        [button("✖️ Отмена", "m:adm")],
    )
