from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/pic"), KeyboardButton(text="Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напишите сообщение",
    )
