from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🎲 Рандом", callback_data="pic"),
            InlineKeyboardButton(text="⬆️ Залить пикчи", callback_data="upload"),
        ]
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
                InlineKeyboardButton(text=f"🅰️ {left_votes}", callback_data=f"duel:{duel_id}:left"),
                InlineKeyboardButton(text=f"🅱️ {right_votes}", callback_data=f"duel:{duel_id}:right"),
            ],
        ]
    )


def picture_actions(image_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="👍", callback_data=f"react:like:{image_id}"),
            InlineKeyboardButton(text="💩", callback_data=f"react:fire:{image_id}"),
            InlineKeyboardButton(text="🖕", callback_data=f"react:dislike:{image_id}"),
        ],
        [InlineKeyboardButton(text="🎲 Ещё", callback_data="pic")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def picture_actions_with_counts(
    image_id: str,
    likes: int,
    fires: int,
    dislikes: int,
) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"react:like:{image_id}"),
            InlineKeyboardButton(text=f"💩 {fires}", callback_data=f"react:fire:{image_id}"),
            InlineKeyboardButton(text=f"🖕 {dislikes}", callback_data=f"react:dislike:{image_id}"),
        ],
        [InlineKeyboardButton(text="🎲 Ещё", callback_data="pic")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
