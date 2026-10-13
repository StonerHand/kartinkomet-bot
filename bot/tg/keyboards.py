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
)
# Telegram truncates long labels on phones: keep ≤ 8 chars with 3 buttons in a row, ≤ 12 with 2.


def button(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    if style:
        return InlineKeyboardButton(text=text, callback_data=data, style=style)
    return InlineKeyboardButton(text=text, callback_data=data)


def markup(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def back(to: str = "m:home") -> list[InlineKeyboardButton]:
    return [button(BACK, to)]


def home(is_admin: bool) -> InlineKeyboardMarkup:
    return markup(
        [button("🎲 Пикчу", "pic", PRIMARY), button("⚔️ Дуэль", "d:new", PRIMARY)],
        [button("🏟 Турнир", "t:new", PRIMARY), button("🎮 Игры", "m:games", PRIMARY)],
        [button("🎰 Казино", "m:casino", SUCCESS), button("🛒 Лавка", "m:shop", SUCCESS)],
        [button("🎁 Бонус", "daily", SUCCESS), button("📜 Квесты", "m:quests")],
        [button("🏆 Рейтинги", "m:top:uploads"), button("👤 Я", "m:me")],
        [button("📥 Загрузить", "m:up"), button("❓ Правила", "m:help")],
        [button("🔄 Обновить", "m:home:refresh")]
        + ([button("⚙️ Админка", "m:adm")] if is_admin else []),
    )


def games_menu() -> InlineKeyboardMarkup:
    return markup(
        [button("🖋 Подпиши", "gm:caption", PRIMARY), button("👹 Босс", "boss", DANGER)],
        [button("🎡 Колесо", "gm:spin", SUCCESS), button("🔮 Гороскоп", "gm:horo")],
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


def casino_menu(presets: tuple[int, ...]) -> InlineKeyboardMarkup:
    games = [button(label, f"cg:{code}", SUCCESS if code == "slots" else None) for code, label in CASINO_BUTTONS]
    stakes = [button(str(amount), f"cs:{amount}") for amount in presets]
    return markup(games[:3], games[3:], stakes, [button("🃏 Ва-банк", "cs:all", DANGER)], back())


def casino_again(game: str, stake: int) -> InlineKeyboardMarkup:
    half = max(10, stake // 2)
    return markup(
        [
            button(f"🔁 {stake}", f"cp:{game}:{stake}", SUCCESS),
            button(f"⏫ {stake * 2}", f"cp:{game}:{stake * 2}"),
            button(f"⏬ {half}", f"cp:{game}:{half}"),
        ]
    )


def pic_menu(token: str, cursed: bool, prices: dict[str, int]) -> InlineKeyboardMarkup:
    """token: a short server-side key for (pic, buyer, chat) — see shop.menu_token."""

    def buy(label: str, item: str, code: str, style: str | None = None) -> InlineKeyboardButton:
        return button(f"{label} {prices[item]}", f"sh:{code}:{token}", style)

    rows = [
        [buy("🛡 Щит", "shield", "s", SUCCESS), buy("⚡ Буст", "boost", "b", PRIMARY)],
        [buy("⚖️ Суд", "court", "c", DANGER), button("🎯 +100", f"sh:h1:{token}")],
        [button("🎯 +500", f"sh:h5:{token}")],
    ]
    if cursed:
        rows[2].append(buy("🧿 Порча", "uncurse", "u", SUCCESS))
    return markup(*rows)


def shop_menu() -> InlineKeyboardMarkup:
    return markup([button("🏷 Купить титул", "title", PRIMARY)], [button("⚰️ Кладбище", "m:grave"), *back()])


def appeal(court_id: str) -> InlineKeyboardMarkup:
    return markup([button("📜 Апелляция", f"ap:{court_id}", PRIMARY), button("🎲 ещё", "pic", PRIMARY)])


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


def open_chests(tiers: list[str]) -> InlineKeyboardMarkup | None:
    if not tiers:
        return None
    return markup([button(CHEST_LABELS[tier], f"ch:{tier}", SUCCESS) for tier in dict.fromkeys(tiers)])


def boss(boss_id: str, price: int) -> InlineKeyboardMarkup:
    return markup([button("🗡 Удар", f"bh:{boss_id}", DANGER), button(f"🔥 Супер {price}", f"bs:{boss_id}", PRIMARY)])


def boss_over() -> InlineKeyboardMarkup:
    return markup([button("🎲 ещё", "pic", PRIMARY), button("🎮 Игры", "m:games")])


def proposal(proposal_id: str) -> InlineKeyboardMarkup:
    return markup([button("💍 Да", f"mr:y:{proposal_id}", SUCCESS), button("💔 Нет", f"mr:n:{proposal_id}", DANGER)])


def release_v4() -> InlineKeyboardMarkup:
    return markup(
        [button("🎁 Бонус", "daily", SUCCESS), button("🎰 Казино", "m:casino", SUCCESS)],
        [button("📜 Квесты", "m:quests"), button("🛒 Лавка", "m:shop")],
    )


def challenge(challenge_id: str) -> InlineKeyboardMarkup:
    return markup(
        [button("✅ Принять", f"cl:y:{challenge_id}", SUCCESS), button("❌ Отказ", f"cl:n:{challenge_id}", DANGER)]
    )


def caption_vote(game_id: str, entries: int) -> InlineKeyboardMarkup:
    buttons = [button(f"{index + 1}", f"cv:{game_id}:{index}", PRIMARY) for index in range(entries)]
    return markup(buttons[:4], buttons[4:])


def after_caption() -> InlineKeyboardMarkup:
    return markup([button("🖋 Ещё пикчу", "gm:caption", PRIMARY)])


def gold(token: str) -> InlineKeyboardMarkup:
    return markup([button("⚡ Забрать", f"gold:{token}", SUCCESS)])


def gold_taken(label: str) -> InlineKeyboardMarkup:
    return markup([button(f"🏆 {label[:10]}", "gold:taken"), button("🎲 ещё", "pic", PRIMARY)])


def after_wheel() -> InlineKeyboardMarkup:
    return markup([button("🎰 В казино", "m:casino", SUCCESS), button("🎲 ещё", "pic", PRIMARY)])


def pic_actions(pic_id: str, likes: int, dislikes: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(f"🤙🏻 {likes}", f"r:+:{pic_id}", SUCCESS),
            button(f"🖕🏻 {dislikes}", f"r:-:{pic_id}", DANGER),
            button("🛒", f"pm:{pic_id}"),
            button("🎲 ещё", "pic", PRIMARY),
        ]
    )


def on_trial() -> InlineKeyboardMarkup:
    return markup([button("⚖️ Идёт суд", "trial", DANGER), button("🎲 ещё", "pic", PRIMARY)])


def more_only() -> InlineKeyboardMarkup:
    return markup([button("🎲 ещё", "pic", PRIMARY)])


def battle_vote(battle_id: str, kind: str, counts: list[int]) -> InlineKeyboardMarkup:
    labels = DUEL_LABELS if kind == "duel" else TOURNAMENT_LABELS
    buttons = [
        button(f"{labels[slot]} {count}", f"v:{battle_id}:{slot}", SLOT_STYLES[slot])
        for slot, count in enumerate(counts)
    ]
    stake = "+50" if len(counts) == 2 else ""
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
    rows = []
    row: list[InlineKeyboardButton] = []
    for index, pic_id in enumerate(pic_ids, start=1):
        row.append(button(f"👀 {index}", f"show:{pic_id}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    rows.append(row)
    rows.append(back("m:top:uploads"))
    return markup(*rows)


def bottom(pic_ids: list[str]) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for index, pic_id in enumerate(pic_ids, start=1):
        row.append(button(f"⚖️ {index}", f"c:go:{pic_id}", DANGER))
        if len(row) == 5:
            rows.append(row)
            row = []
    rows.append(row)
    rows.append(back("m:top:uploads"))
    return markup(*rows)


def graveyard(pic_ids: list[str], is_admin: bool) -> InlineKeyboardMarkup:
    rows = [[button(f"🧟 {index}", f"res:{pic_id}") for index, pic_id in enumerate(pic_ids, start=1)]]
    if is_admin:
        rows.append(
            [
                button(f"🕊 {index}", f"adm:spare:{pic_id}", SUCCESS)
                for index, pic_id in enumerate(pic_ids, start=1)
            ]
        )
    rows.append(back("m:top:uploads"))
    return markup(*rows)


def tops(active: str) -> InlineKeyboardMarkup:
    tabs = [
        button(("✅ " + label.split(" ", 1)[1]) if board == active else label, f"m:top:{board}")
        for board, label in TOP_BOARDS
    ]
    pics = [button("🏛 Слава", "m:hall"), button("🕳 Дно", "m:bottom"), button("⚰️ Морг", "m:grave")]
    return markup(tabs[:2], tabs[2:4], tabs[4:], pics, back())


def upload_hub(is_private: bool) -> InlineKeyboardMarkup:
    if is_private:
        return markup([button("📥 Начать загрузку", "up:start", SUCCESS)], back())
    return markup(back())


def uploading() -> InlineKeyboardMarkup:
    return markup([button("✅ Готово", "up:done", SUCCESS), button("❌ Отмена", "up:cancel", DANGER)])


def admin(events_on: bool | None = None) -> InlineKeyboardMarkup:
    """events_on is None in private chats, where scheduled events don't apply."""
    events_row = []
    if events_on is not None:
        label = "🔔 События: вкл" if events_on else "🔕 События: выкл"
        events_row = [button(label, "adm:events", SUCCESS if events_on else None)]
    return markup(
        [button("🩺 Health", "adm:health"), button("💾 Бэкап", "adm:backup")],
        events_row,
        [button("🧨 Сбросить статистику", "adm:reset", DANGER)],
        back(),
    )


def admin_reset_confirm() -> InlineKeyboardMarkup:
    return markup(
        [button("💀 Да, всё стереть", "adm:reset!", DANGER)],
        [button("Отмена", "m:adm")],
    )
