from functools import lru_cache

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(
    is_private: bool = False,
    image_duel_active: bool = False,
    tournament_active: bool = False,
    image_duel_seconds: int | None = None,
    tournament_seconds: int | None = None,
) -> InlineKeyboardMarkup:
    arena_seconds = [
        seconds
        for active, seconds in [
            (image_duel_active, image_duel_seconds),
            (tournament_active, tournament_seconds),
        ]
        if active and seconds is not None
    ]
    arena_active = image_duel_active or tournament_active
    arena_label = (
        active_button_text("⚔️ Арены", True, min(arena_seconds))
        if arena_seconds
        else active_button_text("⚔️ Арены", arena_active)
    )
    keyboard = [
        [
            InlineKeyboardButton(text="🎲 Выдача", callback_data="menu_random"),
            InlineKeyboardButton(text=arena_label, callback_data="menu_arena"),
        ],
        [
            InlineKeyboardButton(text="📦 Склад", callback_data="menu_storage"),
            InlineKeyboardButton(text="📥 Загрузка", callback_data="upload_hub"),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def random_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Пикча", callback_data="pic"),
            ],
            [
                InlineKeyboardButton(text="🎛 Назад в пульт", callback_data="menu"),
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
                InlineKeyboardButton(text=image_duel_label, callback_data="duel_new"),
                InlineKeyboardButton(text=tournament_label, callback_data="tournament_new"),
            ],
            [
                InlineKeyboardButton(text="📊 Сводка", callback_data="stats"),
                InlineKeyboardButton(text="🎛 Назад в пульт", callback_data="menu"),
            ],
        ]
    )


def storage_menu(is_private: bool = False) -> InlineKeyboardMarkup:
    upload_label = "📥 Загрузка" if is_private else "📬 В личку"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 Склад", callback_data="count"),
                InlineKeyboardButton(text=upload_label, callback_data="upload_hub"),
            ],
            [
                InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
                InlineKeyboardButton(text="👤 Мой вклад", callback_data="me"),
            ],
            [
                InlineKeyboardButton(text="🎛 Назад в пульт", callback_data="menu"),
            ],
        ]
    )


def upload_hub(is_private: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Пикчи" if is_private else "📬 Пикчи в личку",
                    callback_data="upload",
                ),
            ],
            [
                InlineKeyboardButton(text="🎛 Назад в пульт", callback_data="menu"),
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
                InlineKeyboardButton(text="✅ Закончить", callback_data="done"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_upload"),
            ],
        ]
    )


def empty_picture_pool_actions(is_private: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Пикчи" if is_private else "📬 Как загрузить пикчи",
                    callback_data="upload",
                ),
            ],
            [
                InlineKeyboardButton(text="🎛 Пульт", callback_data="menu"),
            ],
        ]
    )


def duel_vote(duel_id: str, left_votes: int = 0, right_votes: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🅰️ Первый: {left_votes}",
                    callback_data=f"duel:{duel_id}:left",
                ),
                InlineKeyboardButton(
                    text=f"🅱️ Второй: {right_votes}",
                    callback_data=f"duel:{duel_id}:right",
                ),
            ],
        ]
    )


@lru_cache(maxsize=1)
def new_duel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚔️ Реванш", callback_data="duel_new"),
                InlineKeyboardButton(text="🎲 Ещё", callback_data="pic"),
            ],
            [
                InlineKeyboardButton(text="🏟 Турнир", callback_data="tournament_new"),
                InlineKeyboardButton(text="🎛 Пульт", callback_data="menu"),
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
                InlineKeyboardButton(
                    text=f"1️⃣ Первая: {counts[0]}",
                    callback_data=f"tournament:{tournament_id}:0",
                ),
                InlineKeyboardButton(
                    text=f"2️⃣ Вторая: {counts[1]}",
                    callback_data=f"tournament:{tournament_id}:1",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"3️⃣ Третья: {counts[2]}",
                    callback_data=f"tournament:{tournament_id}:2",
                ),
                InlineKeyboardButton(
                    text=f"4️⃣ Четвёртая: {counts[3]}",
                    callback_data=f"tournament:{tournament_id}:3",
                ),
            ],
        ]
    )


def new_tournament(winner_id: str | None = None) -> InlineKeyboardMarkup:
    duel_button = (
        InlineKeyboardButton(
            text="⚔️ Чемпион",
            callback_data=f"duel_champion:{winner_id}",
        )
        if winner_id
        else InlineKeyboardButton(text="⚔️ Дуэль", callback_data="duel_new")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏟 Реванш", callback_data="tournament_new"),
                InlineKeyboardButton(text="🎲 Ещё", callback_data="pic"),
            ],
            [
                duel_button,
                InlineKeyboardButton(text="🎛 Пульт", callback_data="menu"),
            ],
        ]
    )


def picture_actions(image_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🤙🏻", callback_data=f"react:like:{image_id}"),
            InlineKeyboardButton(text="🖕🏻", callback_data=f"react:dislike:{image_id}"),
        ],
        [
            InlineKeyboardButton(text="🎲 Ещё", callback_data="pic"),
            InlineKeyboardButton(text="⚔️ Дуэль", callback_data="duel_new"),
            InlineKeyboardButton(text="🏟 Турнир", callback_data="tournament_new"),
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
            InlineKeyboardButton(
                text=f"🤙🏻 {likes}",
                callback_data=f"react:like:{image_id}",
            ),
            InlineKeyboardButton(
                text=f"🖕🏻 {dislikes}",
                callback_data=f"react:dislike:{image_id}",
            ),
        ],
        [
            InlineKeyboardButton(text="🎲 Ещё", callback_data="pic"),
            InlineKeyboardButton(text="⚔️ Дуэль", callback_data="duel_new"),
            InlineKeyboardButton(text="🏟 Турнир", callback_data="tournament_new"),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
