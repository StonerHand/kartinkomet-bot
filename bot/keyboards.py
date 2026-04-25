from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
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
            [InlineKeyboardButton(text="✅ Закончить", callback_data="done")],
        ]
    )


def picture_actions(image_id: str, is_admin: bool) -> InlineKeyboardMarkup | None:
    keyboard = [
        [
            InlineKeyboardButton(text="👍", callback_data=f"react:like:{image_id}"),
            InlineKeyboardButton(text="💩", callback_data=f"react:fire:{image_id}"),
            InlineKeyboardButton(text="🖕", callback_data=f"react:dislike:{image_id}"),
        ]
    ]

    if is_admin:
        keyboard.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{image_id}")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def picture_actions_with_counts(
    image_id: str,
    is_admin: bool,
    likes: int,
    fires: int,
    dislikes: int,
) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"react:like:{image_id}"),
            InlineKeyboardButton(text=f"💩 {fires}", callback_data=f"react:fire:{image_id}"),
            InlineKeyboardButton(text=f"🖕 {dislikes}", callback_data=f"react:dislike:{image_id}"),
        ]
    ]

    if is_admin:
        keyboard.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{image_id}")])

    return InlineKeyboardMarkup(
        inline_keyboard=keyboard
    )
