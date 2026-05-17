from functools import lru_cache

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(
    is_private: bool = False,
    image_duel_active: bool = False,
    joke_duel_active: bool = False,
    tournament_active: bool = False,
    image_duel_seconds: int | None = None,
    joke_duel_seconds: int | None = None,
    tournament_seconds: int | None = None,
) -> InlineKeyboardMarkup:
    upload_row = [
        InlineKeyboardButton(
            text="📥 Пикчи" if is_private else "📬 Пикчи",
            callback_data="upload",
        ),
        InlineKeyboardButton(
            text="📝 Шутки",
            callback_data="upload_joke",
        ),
    ]
    random_row = [
        InlineKeyboardButton(text="🎲 Пикча", callback_data="pic"),
        InlineKeyboardButton(text="😂 Шутка", callback_data="joke"),
    ]
    duel_row = [
        InlineKeyboardButton(
            text=active_button_text("⚔️ Пикчи", image_duel_active, image_duel_seconds)
            if image_duel_active
            else "⚔️ Дуэль пикч",
            callback_data="duel_new",
        ),
        InlineKeyboardButton(
            text=active_button_text("🥊 Шутки", joke_duel_active, joke_duel_seconds)
            if joke_duel_active
            else "🥊 Дуэль шуток",
            callback_data="joke_duel_new",
        ),
    ]
    utility_rows = [
        [
            InlineKeyboardButton(
                text=active_button_text("🏟 Турнир", tournament_active, tournament_seconds)
                if tournament_active
                else "🏟 Турнир",
                callback_data="tournament_new",
            ),
            InlineKeyboardButton(text="📊 Сводка", callback_data="stats"),
        ],
        [
            InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
            InlineKeyboardButton(text="🌦 Погода", callback_data="weather"),
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="me"),
        ],
    ]
    keyboard = (
        [upload_row, random_row, duel_row, *utility_rows]
        if is_private
        else [random_row, duel_row, *utility_rows, upload_row]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


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
                InlineKeyboardButton(text="😂 Шутка", callback_data="joke"),
                InlineKeyboardButton(text="🎛 Пульт", callback_data="menu"),
            ],
        ]
    )


def empty_joke_pool_actions(is_private: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Шутки" if is_private else "📬 Как загрузить шутки",
                    callback_data="upload_joke",
                ),
            ],
            [
                InlineKeyboardButton(text="🎲 Пикча", callback_data="pic"),
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
            [InlineKeyboardButton(text="⚔️ Реванш пикч", callback_data="duel_new")],
        ]
    )


def joke_duel_vote(
    duel_id: str,
    left_votes: int = 0,
    right_votes: int = 0,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🅰️ Первый: {left_votes}",
                    callback_data=f"joke_duel:{duel_id}:left",
                ),
                InlineKeyboardButton(
                    text=f"🅱️ Второй: {right_votes}",
                    callback_data=f"joke_duel:{duel_id}:right",
                ),
            ],
        ]
    )


@lru_cache(maxsize=1)
def new_joke_duel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥊 Реванш шуток", callback_data="joke_duel_new")],
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


@lru_cache(maxsize=1)
def new_tournament() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏟 Новый турнир", callback_data="tournament_new")],
        ]
    )


def picture_actions(image_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🤙🏻", callback_data=f"react:like:{image_id}"),
            InlineKeyboardButton(text="🖕🏻", callback_data=f"react:dislike:{image_id}"),
        ],
        [InlineKeyboardButton(text="🎲 Ещё", callback_data="pic")],
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
        [InlineKeyboardButton(text="🎲 Ещё", callback_data="pic")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def joke_actions(joke_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🤙🏻", callback_data=f"joke_react:like:{joke_id}"),
            InlineKeyboardButton(text="🖕🏻", callback_data=f"joke_react:dislike:{joke_id}"),
        ],
        [InlineKeyboardButton(text="😂 Ещё", callback_data="joke")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def joke_actions_with_counts(
    joke_id: str,
    likes: int,
    dislikes: int,
) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"🤙🏻 {likes}",
                callback_data=f"joke_react:like:{joke_id}",
            ),
            InlineKeyboardButton(
                text=f"🖕🏻 {dislikes}",
                callback_data=f"joke_react:dislike:{joke_id}",
            ),
        ],
        [InlineKeyboardButton(text="😂 Ещё", callback_data="joke")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
