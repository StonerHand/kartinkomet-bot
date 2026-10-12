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
TOURNAMENT_LABELS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")
TOP_BOARDS = (("uploads", "📥 Загрузчики"), ("loved", "❤️ Любимцы"), ("killers", "🪓 Палачи"), ("streaks", "🔥 Серии"))


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
        [
            button("🎲 Пикчу", "pic", PRIMARY),
            button("⚔️ Дуэль", "d:new", PRIMARY),
            button("🏟 Турнир", "t:new", PRIMARY),
        ],
        [
            button("🏛 Зал славы", "m:hall"),
            button("🕳 Дно склада", "m:bottom"),
            button("⚰️ Кладбище", "m:grave"),
        ],
        [
            button("🏆 Топы", "m:top:uploads"),
            button("👤 Я", "m:me"),
            button("📥 Загрузить", "m:up", SUCCESS),
        ],
        [button("⚙️ Админка", "m:adm")] if is_admin else [],
    )


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
        button(f"{labels[slot]} {count}", f"v:{battle_id}:{slot}", PRIMARY)
        for slot, count in enumerate(counts)
    ]
    return markup(buttons)


def after_duel(battle_id: str, has_champion: bool) -> InlineKeyboardMarkup:
    row = [button("⚔️ Новая дуэль", "d:new", PRIMARY)]
    if has_champion:
        row.insert(0, button("👑 Чемпион дальше", f"d:ch:{battle_id}", SUCCESS))
    return markup(row)


def after_tournament() -> InlineKeyboardMarkup:
    return markup([button("🏟 Ещё турнир", "t:new", PRIMARY)])


def court_vote(court_id: str, kill: int, spare: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(f"🪓 Казнить {kill}", f"c:k:{court_id}", DANGER),
            button(f"🕊 Помиловать {spare}", f"c:s:{court_id}", SUCCESS),
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
        button(("• " if board == active else "") + label, f"m:top:{board}")
        for board, label in TOP_BOARDS
    ]
    return markup(tabs[:2], tabs[2:], back())


def upload_hub(is_private: bool) -> InlineKeyboardMarkup:
    if is_private:
        return markup([button("📥 Начать загрузку", "up:start", SUCCESS)], back())
    return markup(back())


def uploading() -> InlineKeyboardMarkup:
    return markup([button("✅ Готово", "up:done", SUCCESS), button("❌ Отмена", "up:cancel", DANGER)])


def admin() -> InlineKeyboardMarkup:
    return markup(
        [button("🩺 Health", "adm:health"), button("💾 Бэкап", "adm:backup")],
        [button("🧨 Сбросить стату", "adm:reset", DANGER)],
        back(),
    )


def admin_reset_confirm() -> InlineKeyboardMarkup:
    return markup(
        [button("💀 Да, всё стереть", "adm:reset!", DANGER), button("Отмена", "m:adm")]
    )
