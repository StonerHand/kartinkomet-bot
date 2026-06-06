from functools import lru_cache

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

STYLE_PRIMARY = "primary"
STYLE_SUCCESS = "success"
STYLE_DANGER = "danger"


def styled_button(
    text: str,
    callback_data: str,
    style: str | None = None,
) -> InlineKeyboardButton:
    data = {"text": text, "callback_data": callback_data}
    if style:
        data["style"] = style
    return InlineKeyboardButton(**data)


def main_menu(
    is_private: bool = False,
    is_admin: bool = False,
    image_duel_active: bool = False,
    tournament_active: bool = False,
    image_duel_seconds: int | None = None,
    tournament_seconds: int | None = None,
) -> InlineKeyboardMarkup:
    duel_label = (
        active_button_text("⚔️ Дуэль", image_duel_active, image_duel_seconds)
        if image_duel_active
        else "⚔️ Дуэль"
    )
    tournament_label = (
        active_button_text("🏟 Турнир", tournament_active, tournament_seconds)
        if tournament_active
        else "🏟 Турнир"
    )
    keyboard = [
        [
            styled_button("🎲 Рандом", "menu_random", STYLE_PRIMARY),
            styled_button(duel_label, "duel_new", STYLE_PRIMARY),
        ],
        [
            styled_button(tournament_label, "tournament_new", STYLE_PRIMARY),
            styled_button("📦 Склад", "menu_storage", STYLE_PRIMARY),
        ],
        [
            styled_button("📊 Сводка", "stats", STYLE_PRIMARY),
            styled_button("📥 Загрузка", "upload_hub", STYLE_SUCCESS),
        ],
    ]
    if is_private and is_admin:
        keyboard.append(
            [
                styled_button("🧰 Админка", "admin_menu", STYLE_PRIMARY),
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def random_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("🎲 Рандомная пикча", "pic", STYLE_PRIMARY),
            ],
            [
                styled_button("↩️ Пульт", "menu"),
            ],
        ]
    )


def arena_menu(
    image_duel_active: bool = False,
    tournament_active: bool = False,
    image_duel_seconds: int | None = None,
    tournament_seconds: int | None = None,
) -> InlineKeyboardMarkup:
    image_duel_label = (
        active_button_text("⚔️ Пикч-бой", image_duel_active, image_duel_seconds)
        if image_duel_active
        else "⚔️ Пикч-бой"
    )
    tournament_label = (
        active_button_text("🏟 Турнир", tournament_active, tournament_seconds)
        if tournament_active
        else "🏟 Турнир"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(image_duel_label, "duel_new", STYLE_PRIMARY),
                styled_button(tournament_label, "tournament_new", STYLE_PRIMARY),
            ],
            [
                styled_button("📊 Сводка арен", "stats", STYLE_PRIMARY),
                styled_button("↩️ Пульт", "menu"),
            ],
        ]
    )


def storage_menu(is_private: bool = False) -> InlineKeyboardMarkup:
    upload_label = "📥 Загрузить" if is_private else "📬 В личку"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("📦 Счётчик", "count", STYLE_PRIMARY),
                styled_button(upload_label, "upload_hub", STYLE_SUCCESS),
            ],
            [
                styled_button("🏆 Топ", "top", STYLE_PRIMARY),
                styled_button("👤 Мой вклад", "me", STYLE_PRIMARY),
            ],
            [
                styled_button("↩️ Пульт", "menu"),
            ],
        ]
    )


def upload_hub(is_private: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(
                    "📥 Начать загрузку" if is_private else "📬 Загрузка в личке",
                    "upload",
                    STYLE_SUCCESS,
                ),
            ],
            [
                styled_button("↩️ Пульт", "menu"),
            ],
        ]
    )


def active_button_text(label: str, active: bool, seconds: int | None = None) -> str:
    if not active:
        return label
    if seconds is None:
        return f"{label} · идёт"
    return f"{label} · {format_button_timer(seconds)}"


def format_button_timer(seconds: int) -> str:
    safe_seconds = max(0, seconds)
    minutes, seconds_left = divmod(safe_seconds, 60)
    return f"{minutes:02d}:{seconds_left:02d}"


@lru_cache(maxsize=1)
def upload_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("✅ Закончить", "done", STYLE_SUCCESS),
                styled_button("❌ Отмена", "cancel_upload", STYLE_DANGER),
            ],
        ]
    )


def empty_picture_pool_actions(is_private: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(
                    "📥 Начать загрузку" if is_private else "📬 Как загрузить пикчи",
                    "upload",
                    STYLE_SUCCESS,
                ),
            ],
            [
                styled_button("🎛 Пульт", "menu"),
            ],
        ]
    )


def duel_vote(duel_id: str, left_votes: int = 0, right_votes: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(f"🅰️ Первый: {left_votes}", f"duel:{duel_id}:left", STYLE_PRIMARY),
                styled_button(f"🅱️ Второй: {right_votes}", f"duel:{duel_id}:right", STYLE_PRIMARY),
            ],
        ]
    )


@lru_cache(maxsize=1)
def new_duel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("⚔️ Реванш", "duel_new", STYLE_SUCCESS),
                styled_button("🎲 Рандом", "pic", STYLE_PRIMARY),
            ],
            [
                styled_button("🏟 Турнир", "tournament_new", STYLE_PRIMARY),
                styled_button("🎛 Пульт", "menu"),
            ],
        ]
    )


def tournament_vote(
    tournament_id: str,
    votes: list[int] | None = None,
) -> InlineKeyboardMarkup:
    counts = votes or [0, 0, 0, 0]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(
                    f"1️⃣ Первая: {counts[0]}",
                    f"tournament:{tournament_id}:0",
                    STYLE_PRIMARY,
                ),
                styled_button(
                    f"2️⃣ Вторая: {counts[1]}",
                    f"tournament:{tournament_id}:1",
                    STYLE_PRIMARY,
                ),
            ],
            [
                styled_button(
                    f"3️⃣ Третья: {counts[2]}",
                    f"tournament:{tournament_id}:2",
                    STYLE_PRIMARY,
                ),
                styled_button(
                    f"4️⃣ Четвёртая: {counts[3]}",
                    f"tournament:{tournament_id}:3",
                    STYLE_PRIMARY,
                ),
            ],
        ]
    )


def new_tournament(winner_id: str | None = None) -> InlineKeyboardMarkup:
    duel_button = (
        styled_button("⚔️ Чемпион", f"duel_champion:{winner_id}", STYLE_SUCCESS)
        if winner_id
        else styled_button("⚔️ Дуэль", "duel_new", STYLE_PRIMARY)
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("🏟 Реванш", "tournament_new", STYLE_SUCCESS),
                styled_button("🎲 Рандом", "pic", STYLE_PRIMARY),
            ],
            [
                duel_button,
                styled_button("🎛 Пульт", "menu"),
            ],
        ]
    )


def picture_actions(image_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            styled_button("🤙🏻", f"react:like:{image_id}", STYLE_SUCCESS),
            styled_button("🖕🏻", f"react:dislike:{image_id}", STYLE_DANGER),
        ],
        [
            styled_button("🎲 Рандом", "pic", STYLE_PRIMARY),
            styled_button("⚔️ Дуэль", "duel_new", STYLE_PRIMARY),
            styled_button("🏟 Турнир", "tournament_new", STYLE_PRIMARY),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def picture_actions_with_counts(
    image_id: str,
    likes: int,
    dislikes: int,
) -> InlineKeyboardMarkup:
    keyboard = [
        [
            styled_button(f"🤙🏻 {likes}", f"react:like:{image_id}", STYLE_SUCCESS),
            styled_button(f"🖕🏻 {dislikes}", f"react:dislike:{image_id}", STYLE_DANGER),
        ],
        [
            styled_button("🎲 Рандом", "pic", STYLE_PRIMARY),
            styled_button("⚔️ Дуэль", "duel_new", STYLE_PRIMARY),
            styled_button("🏟 Турнир", "tournament_new", STYLE_PRIMARY),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@lru_cache(maxsize=1)
def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("🩺 Health", "admin_health", STYLE_PRIMARY),
                styled_button("🗄 Бэкап", "admin_backup", STYLE_SUCCESS),
            ],
            [
                styled_button("♻️ Сброс стат", "admin_reset", STYLE_DANGER),
                styled_button("🧹 Дубли", "admin_dedupe", STYLE_PRIMARY),
            ],
            [
                styled_button("🎛 Пульт", "menu"),
            ],
        ]
    )
