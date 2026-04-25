from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="Картинка", callback_data="pic"),
            InlineKeyboardButton(text="Количество", callback_data="count"),
        ],
    ]

    if is_admin:
        keyboard.append(
            [
                InlineKeyboardButton(text="Загрузить", callback_data="upload"),
                InlineKeyboardButton(text="Завершить", callback_data="done"),
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def picture_actions(image_id: str, is_admin: bool) -> InlineKeyboardMarkup | None:
    if not is_admin:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Удалить из пула", callback_data=f"delete:{image_id}")],
        ]
    )


def reply_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/pic"), KeyboardButton(text="/count")],
            [KeyboardButton(text="Меню")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напишите команду",
    )
