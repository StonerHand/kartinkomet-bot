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
        [button("🏟 Турнир", "t:new", PRIMARY), button("🏆 Топы", "m:top:uploads")],
        [button("🏛 Слава", "m:hall"), button("🕳 Дно", "m:bottom")],
        [button("⚰️ Кладбище", "m:grave"), button("👤 Я", "m:me")],
        [button("🎮 Игры", "m:games", PRIMARY), button("❓ Правила", "m:help")],
        [button("📥 Загрузить", "m:up", SUCCESS)],
        [button("🔄 Обновить", "m:home:refresh")]
        + ([button("⚙️ Админка", "m:adm")] if is_admin else []),
    )


def games_menu() -> InlineKeyboardMarkup:
    return markup(
        [button("🖋 Подпиши", "gm:caption", PRIMARY), button("🎰 Колесо", "gm:spin", SUCCESS)],
        [button("🔮 Гороскоп", "gm:horo")],
        back(),
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


def spin_again(price: int) -> InlineKeyboardMarkup:
    label = "🎰 Ещё раз" if not price else f"🎰 За {price} 🪙"
    return markup([button(label, "gm:spin", SUCCESS)])


def pic_actions(pic_id: str, likes: int, dislikes: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(f"🤙🏻 {likes}", f"r:+:{pic_id}", SUCCESS),
            button(f"🖕🏻 {dislikes}", f"r:-:{pic_id}", DANGER),
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
    return markup(buttons)


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
    rows.append(back())
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
    rows.append(back())
    return markup(*rows)


def graveyard(pic_ids: list[str], is_admin: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_admin:
        rows.append(
            [
                button(f"🕊 {index}", f"adm:spare:{pic_id}", SUCCESS)
                for index, pic_id in enumerate(pic_ids, start=1)
            ]
        )
    rows.append(back())
    return markup(*rows)


def tops(active: str) -> InlineKeyboardMarkup:
    tabs = [
        button(("✅ " + label.split(" ", 1)[1]) if board == active else label, f"m:top:{board}")
        for board, label in TOP_BOARDS
    ]
    return markup(tabs[:2], tabs[2:4], tabs[4:], back())


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
