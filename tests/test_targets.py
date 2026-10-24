"""Commands aimed at people: the bot asks whom and how much, takes a name or a number in reply,
finds people by username, first name or a mention, and keeps the chat clean where it can't
write personally."""

import asyncio
import json
from datetime import UTC, datetime

from aiogram.types import Message, MessageEntity, User

from bot.tg import send, targets
from tests.test_bot import BOT_USER, GROUP
from tests.test_v5_edges import Harness


class Players(Harness):
    """A chat the bot knows three people in. Helpers only."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        for player in (4, 5):  # the chat has met them: a button press is enough
            await self.press("noop", sender=player)
            self.clock.advance(1)
        self.game.repo.remember_user(7, None, "Данил", "Медведев", self.game.now())
        self.game.repo.touch_member(-100, 7, self.game.now())
        for player in (3, 4, 5, 7):
            self.fund(player, 1000 if player == 3 else 500)

    def question(self) -> dict:
        return json.loads(self.game.repo.meta_str("ask:-100:3"))

    def bot_message(self, message_id: int) -> Message:
        return Message(message_id=message_id, date=datetime.now(UTC), chat=GROUP, from_user=BOT_USER, text="?")


class TargetsTest(Players):
    async def test_rob_from_the_menu_asks_whom_and_a_button_answers(self) -> None:
        self.fund(5, 1000)
        await self.send("/rob@kartinkomet_bot", sender=3)
        question = self.session.of("SendEphemeralMessage")[-1]
        self.assertEqual(question.ephemeral_message_parameters.receiver_user_id, 3)
        self.assertIn("КОГО ГРАБИМ?", question.text)
        labels = [button.text for row in question.reply_markup.inline_keyboard for button in row]
        self.assertEqual(labels, ["Данил Медведев", "user5", "user4", "✖️ Отмена"])  # most recent first, not the robber
        await self.press(self.buttons(question)[1], sender=4)  # someone else's question
        self.assertIn("не тебе", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(self.buttons(question)[1], sender=3)
        self.assertTrue(any("ОГРАБЛЕНИЕ" in request.text for request in self.session.of("SendMessage")))
        self.assertIsNone(targets.pending(self.game, -100, 3))
        await self.press(self.buttons(question)[1], sender=3)  # a second tap on the old question
        self.assertIn("устарел", self.session.of("AnswerCallbackQuery")[-1].text)

    async def test_give_asks_whom_then_how_much(self) -> None:
        await self.send("/give", sender=3)
        await self.press(self.buttons(self.session.of("SendEphemeralMessage")[-1])[2], sender=3)  # user4
        amounts = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("СКОЛЬКО ДАРИМ?", amounts.text)
        self.assertIn("user4", amounts.text)
        self.assertIsNotNone(amounts.ephemeral_message_parameters.callback_query_id)  # allowed without admin rights
        await self.press(self.buttons(amounts)[1], sender=3)  # 500
        self.assertIn("ПОДАРОК", self.session.of("SendMessage")[-1].text)
        self.assertEqual((self.coins(3), self.coins(4)), (500, 1000))

    async def test_rob_offers_only_people_worth_robbing(self) -> None:
        self.game.repo.add_coins(5, -450, "test", self.game.now(), earn=False)  # 50 left: too poor
        await self.send("/rob", sender=3)
        labels = [button.text for row in self.session.of("SendEphemeralMessage")[-1].reply_markup.inline_keyboard
                  for button in row]
        self.assertEqual(labels, ["Данил Медведев", "user4", "✖️ Отмена"])

    async def test_a_jailed_robber_hears_it_before_picking(self) -> None:
        self.game.repo.set_counter(3, "jail_until", self.game.now() + 600)
        await self.send("/rob", sender=3)
        self.assertIn("обезьяннике", self.session.of("SendEphemeralMessage")[-1].text)
        self.assertIsNone(targets.pending(self.game, -100, 3))

    async def test_cancel_leaves_no_trace(self) -> None:
        await self.send("/marry", sender=3)
        await self.press(self.buttons(self.session.of("SendEphemeralMessage")[-1])[-1], sender=3)
        self.assertEqual(self.session.of("AnswerCallbackQuery")[-1].text, "Отменено")
        self.assertIsNone(targets.pending(self.game, -100, 3))
        self.assertFalse(self.session.of("SendMessage"))

    async def test_names_mentions_and_full_names(self) -> None:
        for text, receiver in (("/give @USER4 10", 4), ("/give данил 10", 7), ("/give 10 Данил Медведев", 7)):
            await self.send(text, sender=3)
            self.assertIn("ПОДАРОК", self.session.of("SendMessage")[-1].text, text)
            self.assertIn(self.game.repo.user_label(receiver), self.session.of("SendMessage")[-1].text)
        # Someone without a username, picked from the @ list: Telegram attaches the person.
        text = "/give Вася 10"
        mention = MessageEntity(type="text_mention", offset=6, length=4,
                                user=User(id=8, is_bot=False, first_name="Вася"))
        await self.dispatcher.feed_update(self.bot, self.update(text, entities=[mention]))
        self.assertIn("Вася", self.session.of("SendMessage")[-1].text)
        self.assertEqual(self.coins(8), 10)

    def update(self, text: str, entities: list[MessageEntity]):
        from aiogram.types import Update

        from tests.test_bot import user

        message = Message(message_id=next(self.session.ids), date=datetime.now(UTC), chat=GROUP, from_user=user(3),
                          text=text, entities=entities)
        return Update(update_id=next(self.update_ids), message=message)

    async def test_unknown_name_is_said_and_people_are_offered(self) -> None:
        await self.send("/rob @kcifekzhue", sender=3)
        question = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("Не знаю, кто такой kcifekzhue", question.text)
        self.assertIn("КОГО ГРАБИМ?", question.text)
        await self.send("/pvp 200 kcifekzhue", sender=3)  # no open challenge for a typo
        self.assertIn("Не знаю, кто такой", self.session.of("SendEphemeralMessage")[-1].text)
        self.assertEqual(self.coins(3), 1000)


class NotAdminTest(Players):
    """The bot isn't a chat admin: Telegram allows personal messages only after a button press."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.session.bot_admin = False

    async def test_a_reply_with_a_nick_answers_the_question(self) -> None:
        self.fund(4, 1000)
        await self.send("/rob", sender=3)
        question = self.session.of("SendMessage")[-1]  # public: nothing triggered a personal one
        self.assertIn("КОГО ГРАБИМ?", question.text)
        asked = self.question()["message"]
        await self.send("@user4", sender=3, reply_to=self.bot_message(asked))
        self.assertTrue(any("ОГРАБЛЕНИЕ" in request.text for request in self.session.of("SendMessage")))
        self.assertIn(asked, [request.message_id for request in self.session.of("DeleteMessage")])  # the question left

    async def test_a_pending_question_doesnt_swallow_other_replies(self) -> None:
        await self.send("/rob", sender=3)
        await self.send("смешно", sender=3, reply_to=self.bot_message(4242))  # some other message of the bot
        self.assertFalse(any("Не нашёл" in request.text for request in self.session.of("SendMessage")))
        self.assertIsNotNone(targets.pending(self.game, -100, 3))

    async def test_a_reply_with_a_stranger_keeps_the_question(self) -> None:
        await self.send("/rob", sender=3)
        asked = self.question()["message"]
        await self.send("@nobody", sender=3, reply_to=self.bot_message(asked))
        self.assertIn("Не нашёл такого", self.session.of("SendMessage")[-1].text)
        self.assertIsNotNone(targets.pending(self.game, -100, 3))

    async def test_hints_clean_up_after_themselves_and_stop_retrying(self) -> None:
        send.FLEETING_SECONDS = 0
        self.addCleanup(setattr, send, "FLEETING_SECONDS", 60)
        await self.send("/divorce", sender=3)
        await self.send("/divorce", sender=3)
        self.assertEqual(len(self.session.of("SendEphemeralMessage")), 1)  # refused once, then not asked again
        await asyncio.sleep(0.01)
        deleted = {request.message_id for request in self.session.of("DeleteMessage")}
        hints = {sent for sent in deleted if sent}
        self.assertGreaterEqual(len(hints), 4)  # two hints and the two commands they answered

    async def test_making_the_bot_an_admin_lifts_the_pause(self) -> None:
        from aiogram.types import ChatMemberAdministrator, ChatMemberMember, ChatMemberUpdated, Update

        await self.send("/divorce", sender=3)
        self.session.bot_admin = True
        rights = dict(can_be_edited=False, is_anonymous=False, can_manage_chat=True, can_delete_messages=False,
                      can_manage_video_chats=False, can_restrict_members=False, can_promote_members=False,
                      can_change_info=False, can_invite_users=False, can_post_stories=False,
                      can_edit_stories=False, can_delete_stories=False, can_send_welcome_messages=False)
        change = ChatMemberUpdated(
            chat=GROUP, from_user=User(id=1, is_bot=False, first_name="admin"), date=datetime.now(UTC),
            old_chat_member=ChatMemberMember(user=BOT_USER),
            new_chat_member=ChatMemberAdministrator(user=BOT_USER, **rights),
        )
        await self.dispatcher.feed_update(self.bot, Update(update_id=next(self.update_ids), my_chat_member=change))
        await self.send("/divorce", sender=3)
        self.assertIn("не в браке", self.session.of("SendEphemeralMessage")[-1].text)


class PanelPeopleTest(Players):
    """«👥 Люди» in the panel: each button starts an action, the questions come personally."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.session.bot_admin = False  # even so: a button press allows a personal answer

    async def test_buttons_ask_personally_even_without_admin_rights(self) -> None:
        await self.press("m:people", sender=3)
        self.assertIn("ЛЮДИ", self.session.of("EditMessageText")[-1].text)
        await self.press("pp:rob", sender=3)
        question = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("КОГО ГРАБИМ?", question.text)
        self.assertIsNotNone(question.ephemeral_message_parameters.callback_query_id)
        self.assertFalse(self.session.of("SendMessage"))  # nothing in the chat

    async def test_a_duel_asks_with_whom_and_anyone_opens_it(self) -> None:
        await self.press("pp:pvp", sender=3)
        question = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("С КЕМ ИГРАЕМ?", question.text)
        labels = [button.text for row in question.reply_markup.inline_keyboard for button in row]
        self.assertIn("🌍 Любой", labels)
        await self.press(self.buttons(question)[labels.index("🌍 Любой")], sender=3)
        stakes = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("КАКАЯ СТАВКА?", stakes.text)
        await self.press(self.buttons(stakes)[0], sender=3)  # 100
        card = self.session.of("SendMessage")[-1]
        self.assertIn("КОСТИ 1 НА 1", card.text)
        self.assertIsNone(self.game.repo.pending_challenge_of(3)["to_user"])  # open to anyone
        self.assertEqual(self.coins(3), 900)

    async def test_divorce_asks_first_and_refuses_the_single(self) -> None:
        await self.press("pp:divorce", sender=3)
        answer = self.session.of("AnswerCallbackQuery")[-1]
        self.assertTrue(answer.show_alert)
        self.assertIn("не в браке", answer.text)

    async def test_daily_by_button_is_personal(self) -> None:
        await self.press("daily", sender=3)
        card = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("БОНУС ДНЯ", card.text)
        self.assertIsNotNone(card.ephemeral_message_parameters.callback_query_id)
