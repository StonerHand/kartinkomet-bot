from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🎲 Рандом", callback_data="pic"),
            InlineKeyboardButton(text="😂 Анекдот", callback_data="joke"),
        ],
        [
            InlineKeyboardButton(text="⚔️ Дуэль", callback_data="duel_new"),
            InlineKeyboardButton(text="🌦 Погода", callback_data="weather"),
        ],
        [
            InlineKeyboardButton(text="📊 Сводка", callback_data="stats"),
            InlineKeyboardButton(text="👤 Мой вклад", callback_data="me"),
        ],
        [
            InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
        ],
        [
            InlineKeyboardButton(text="📥 Пикчи", callback_data="upload"),
            InlineKeyboardButton(text="📝 Анекдоты", callback_data="upload_joke"),
        ],
    ]

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
