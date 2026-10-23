"""People's court: opening trials, votes, the defendant's last word."""

from html import escape

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from bot.game import Game
from bot.texts import court as court_texts
from bot.texts import toasts
from bot.texts.pick import pick
from bot.tg import keyboards, send, views
from bot.tg.timers import Live

router = Router(name="court")


async def open_court(
    bot: Bot,
    game: Game,
    live: Live,
    chat_id: int,
    pic_id: str,
    reason: str,
    started_by: int | None,
    pic_message_id: int | None = None,
) -> str:
    """Returns 'started' | 'active' | 'immune' | 'gone' | 'failed'."""

    def attempt():
        return game.start_court(
            chat_id,
            pic_id,
            reason,
            started_by,
            title=pick(court_texts.SUMMONS, chat_id),
            pic_message_id=pic_message_id,
        )

    result = attempt()
    if result.status == "active" and result.court and result.court.ends_at <= game.now():
        await live.finish_court(result.court.id)
        result = attempt()
    if result.status != "started" or result.court is None:
        return result.status
    return await launch_court(bot, game, live, result.court, pic_message_id)


async def launch_court(bot: Bot, game: Game, live: Live, trial, pic_message_id: int | None = None) -> str:
    """Send the court card for a court that already exists and start its timer."""
    chat_id = trial.chat_id
    message = await send.send_photo(
        bot,
        chat_id,
        trial.pic.file_id,
        views.court_card(trial, trial.ends_at - game.now(), game.repo.user_label(trial.pic.added_by)),
        keyboards.court_vote(trial.id, 0, 0),
        reply_to=pic_message_id,
    )
    if message is None:
        game.cancel_court(trial.id)
        return "failed"
    game.repo.set_court_message(trial.id, message.message_id)
    if pic_message_id is not None:
        await send.edit_markup(bot, chat_id, pic_message_id, keyboards.on_trial())
    live.watch_court(trial.id)
    return "started"


@router.callback_query(F.data.startswith("c:go:"), F.message)
async def summon_from_bottom(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    pic_id = callback.data.split(":", 2)[2]
    status = await open_court(
        bot, game, live, callback.message.chat.id, pic_id, "bottom", callback.from_user.id
    )
    answers = {
        "started": court_texts.BOTTOM_SUMMONS_ANSWER,
        "active": court_texts.ALREADY_ON_TRIAL,
        "immune": court_texts.IMMUNE,
    }
    if status in answers:
        await callback.answer(pick(answers[status]), show_alert=status != "started")
    elif status == "gone":
        await callback.answer("Её уже нет в живых", show_alert=True)
    else:
        await callback.answer("Telegram не дал открыть суд, попробуй ещё раз", show_alert=True)


@router.callback_query(F.data.regexp(r"^c:[ks]:"))
async def court_vote(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, kind, court_id = callback.data.split(":", 2)
    vote = "kill" if kind == "k" else "spare"
    status, trial = game.vote_court(court_id, callback.from_user.id, vote)
    if status == "expired":
        await callback.answer("Время вышло, приговор оглашается")
        await live.finish_court(court_id)
        return
    if status in ("gone", "closed"):
        await callback.answer("Суд уже окончен", show_alert=True)
        return
    if status == "same":
        await callback.answer(pick(toasts.ALREADY))
        return
    await callback.answer(pick(toasts.KILL_VOTE if vote == "kill" else toasts.SPARE_VOTE))
    live.request_refresh_court(court_id)


@router.callback_query(F.data.startswith("ap:"))
async def appeal(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    court_id = callback.data.split(":", 1)[1]
    result = game.appeal(court_id, callback.from_user.id, title=pick(court_texts.APPEAL, court_id))
    answers = {
        "gone": "Этого приговора уже нет",
        "final": "Это и была апелляция. Приговор окончательный",
        "not_owner": "Апелляцию подаёт только тот, кто загрузил пикчу",
        "late": "Срок апелляции вышел. Пять минут — и всё",
        "broke": f"Залог — {views.num(game.appeal_bail())} 🪙. Столько у тебя нет",
    }
    if result.status != "started" or result.court is None:
        await callback.answer(answers.get(result.status, "Не вышло"), show_alert=True)
        return
    await callback.answer(f"📜 Апелляция подана. Залог {views.num(result.court.bail)} 🪙")
    if callback.message is not None:
        filed = (callback.message.caption or callback.message.text or "").split("\n")[0]
        note = "📜 <b>Подана апелляция</b> — повторный суд ниже"
        edit = send.edit_caption if callback.message.photo else send.edit_text
        if not filed or not await edit(
            bot, callback.message.chat.id, callback.message.message_id, f"{escape(filed)}\n\n{note}", keyboards.more_only()
        ):
            await send.edit_markup(bot, callback.message.chat.id, callback.message.message_id, keyboards.more_only())
    if await launch_court(bot, game, live, result.court) != "started":
        game.undo_appeal(result.court.id)


@router.callback_query(F.data == "trial")
async def trial_placeholder(callback: CallbackQuery) -> None:
    await callback.answer("Пикча под судом. Голосуй в карточке суда", show_alert=True)


@router.message(F.reply_to_message.from_user.is_bot & F.text)
async def reply_to_bot(message: Message, bot: Bot, game: Game, live: Live) -> None:
    """Replies to the bot are either a defendant's last word or a caption-contest entry."""
    if message.from_user is None or message.reply_to_message is None:
        return
    trial = game.last_word(
        message.chat.id,
        message.reply_to_message.message_id,
        message.from_user.id,
        message.text or "",
    )
    if trial is None:
        from bot.tg.games import caption_reply  # local: games imports arena, which shares helpers
        from bot.tg.shop import title_reply

        if not await title_reply(message, bot, game):
            await caption_reply(message, bot, game, live)
        return
    await live.refresh_court(trial.id)
    await message.reply("🗣 Записано в протокол. Присяжные, учтите")
