from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(is_private: bool = False) -> InlineKeyboardMarkup:
    upload_row = [
        InlineKeyboardButton(
            text="📥 Загрузить пикчи" if is_private else "📬 Загрузка пикч",
            callback_data="upload",
        ),
        InlineKeyboardButton(
            text="📝 Загрузить шутки",
            callback_data="upload_joke",
        ),
    ]
    random_row = [
        InlineKeyboardButton(text="🎲 Рандом пикч", callback_data="pic"),
        InlineKeyboardButton(text="😂 Рандом шуток", callback_data="joke"),
    ]
    duel_row = [
        InlineKeyboardButton(text="⚔️ Дуэль пикч", callback_data="duel_new"),
        InlineKeyboardButton(text="🥊 Дуэль шуток", callback_data="joke_duel_new"),
    ]
    utility_rows = [
        [
            InlineKeyboardButton(text="🏟 Турнир", callback_data="tournament_new"),
            InlineKeyboardButton(text="📊 Сводка склада", callback_data="stats"),
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


def upload_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Закончить", callback_data="done"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_upload"),
            ],
        ]
    )


def duel_vote(duel_id: str, left_votes: int = 0, right_votes: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🅰️ Слева · {left_votes}",
                    callback_data=f"duel:{duel_id}:left",
                ),
                InlineKeyboardButton(
                    text=f"🅱️ Справа · {right_votes}",
                    callback_data=f"duel:{duel_id}:right",
                ),
            ],
        ]
    )


def new_duel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Новая дуэль", callback_data="duel_new")],
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
                    text=f"🅰️ Первый · {left_votes}",
                    callback_data=f"joke_duel:{duel_id}:left",
                ),
                InlineKeyboardButton(
                    text=f"🅱️ Второй · {right_votes}",
                    callback_data=f"joke_duel:{duel_id}:right",
                ),
            ],
        ]
    )


def new_joke_duel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="😂 Новая дуэль", callback_data="joke_duel_new")],
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
                    text=f"1️⃣ Первая · {counts[0]}",
                    callback_data=f"tournament:{tournament_id}:0",
                ),
                InlineKeyboardButton(
                    text=f"2️⃣ Вторая · {counts[1]}",
                    callback_data=f"tournament:{tournament_id}:1",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"3️⃣ Третья · {counts[2]}",
                    callback_data=f"tournament:{tournament_id}:2",
                ),
                InlineKeyboardButton(
                    text=f"4️⃣ Четвёртая · {counts[3]}",
                    callback_data=f"tournament:{tournament_id}:3",
                ),
            ],
        ]
    )


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
        [InlineKeyboardButton(text="😂 Ещё анекдот", callback_data="joke")],
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
        [InlineKeyboardButton(text="😂 Ещё анекдот", callback_data="joke")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
