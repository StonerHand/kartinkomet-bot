"""bot/lean.py: aiogram models are built on first use, and every kind of update still parses."""

import unittest

import aiogram.types as types
from aiogram.methods import SendMessage
from aiogram.types import Update

USER = {"id": 1, "is_bot": False, "first_name": "a"}
CHAT = {"id": -100, "type": "supergroup", "title": "чат"}


def message(**extra) -> dict:
    return {"message_id": 1, "date": 0, "chat": CHAT, "from": USER, **extra}


class LeanAiogramTest(unittest.TestCase):
    def test_unused_models_stay_unbuilt(self) -> None:
        self.assertFalse(types.Giveaway.__pydantic_complete__)
        self.assertFalse(types.PaidMediaInfo.__pydantic_complete__)

    def test_rare_message_contents_parse(self) -> None:
        """Whatever lands in the chat must still parse: these models get built right here."""
        contents = [
            {"sticker": {"file_id": "s", "file_unique_id": "u", "type": "regular", "width": 1, "height": 1,
                         "is_animated": False, "is_video": False}},
            {"poll": {"id": "p", "question": "?", "options": [{"text": "a", "voter_count": 0}], "total_voter_count": 0,
                      "is_closed": False, "is_anonymous": True, "type": "regular", "allows_multiple_answers": False}},
            {"location": {"latitude": 1.0, "longitude": 2.0}},
            {"dice": {"emoji": "🎲", "value": 3}},
            {"forward_origin": {"type": "user", "date": 0, "sender_user": USER}, "text": "fwd"},
            {"story": {"chat": CHAT, "id": 1}},
            {"text": "x", "entities": [{"type": "text_mention", "offset": 0, "length": 1, "user": USER}]},
            {"reply_to_message": message(text="reply"), "text": "re"},
            {"document": {"file_id": "d", "file_unique_id": "u"}, "caption": "doc"},
        ]
        for extra in contents:
            with self.subTest(content=next(iter(extra))):
                update = Update.model_validate({"update_id": 1, "message": message(**extra)})
                self.assertEqual(update.message.chat.id, -100)

    def test_callback_and_inline_parse(self) -> None:
        update = Update.model_validate(
            {"update_id": 2, "callback_query": {"id": "1", "from": USER, "chat_instance": "c", "data": "pic",
                                                "message": message(text="card")}}
        )
        self.assertEqual(update.callback_query.data, "pic")
        inline = Update.model_validate({"update_id": 3, "inline_query": {"id": "1", "from": USER, "query": "",
                                                                         "offset": ""}})
        self.assertEqual(inline.inline_query.query, "")

    def test_methods_serialize(self) -> None:
        method = SendMessage(chat_id=-100, text="hi", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text="b", callback_data="x")]]))
        self.assertEqual(method.model_dump(exclude_none=True)["chat_id"], -100)


if __name__ == "__main__":
    unittest.main()
