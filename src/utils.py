import json
import logging
import time

from telegram import Update, Bot, ReplyKeyboardMarkup, ParseMode
import telegram

from telegram.ext import CallbackContext

from src.config import INITIAL_KEYBOARD, MAIN_KEYBOARD, ORGA_KEYBOARD, ORGA_GROUPS

log = logging.getLogger(__name__)


def set_log_level_format(logging_level, format):
    logging.addLevelName(logging_level, format % logging.getLevelName(logging_level))


def get_logging_level(args):
    if args.verbose >= 3:
        return logging.DEBUG
    if args.verbose == 2:
        return logging.INFO
    if args.verbose >= 1:
        return logging.WARNING
    return logging.ERROR


def save_json(data, filename):
    from src.config import SECRETS_DIR

    with open(SECRETS_DIR / filename, "w") as file:
        json.dump(data, file)


def who(update: Update) -> str:
    """Based on `update`, get username and format it to a string."""
    try:
        chat = update.message.chat
    except AttributeError:
        chat = update.callback_query.message.chat
    # username is 'guaranteed' to exist (might be None tho),
    # but first_name and last_name aren't
    first_name = str(chat.to_dict().get("first_name") or "")
    last_name = str(chat.to_dict().get("last_name") or "")
    return f"{first_name} {last_name} <@{chat.username}>"


def dev_msg(message):
    """Send message to developer.

    For longer and formatted messages consider `dev_html` instead.
    """
    from src.config import TOKEN, DEVELOPER_CHAT_ID

    bot = Bot(token=TOKEN)
    log.info(f"to dev: {message}")
    bot.send_message(
        chat_id=DEVELOPER_CHAT_ID,
        text=message,
    )


def channel_msg(message):
    """Send notification to channel for logging purposes."""
    from src.config import TOKEN, UPDATES_CHANNEL_ID

    bot = Bot(token=TOKEN)

    log.info(f"to channel: {message}")
    try:
        bot.send_message(
            chat_id=UPDATES_CHANNEL_ID,
            text=message,
        )
    except telegram.error.RetryAfter as r:
        dev_msg(f"🔴 Flood Control. Backing off for {r.retry_after}s")
        time.sleep(r.retry_after)
        channel_msg(message)


def group_msg(
    update: Update, context: CallbackContext, group: str, message: str
) -> None:
    """Send `message` to all members of `group` except current user
    (in case the user is member of that group).
    """
    log.info(f"to {group}: {message}")
    remove = []
    for chat_id in context.bot_data["group_association"].get(group, []):
        if chat_id == update.effective_chat.id:
            # don't send message to current user
            continue
        try:
            context.bot.send_message(
                chat_id=chat_id,
                text=message,
                reply_markup=autoselect_keyboard(update, context),
            )
        except telegram.error.Unauthorized:
            # user blocked bot.
            text = (
                f"⚠️ Unauthorized for sending message to {chat_id} from "
                f"{context.user_data['group_association']} in list of [{group}]. "
                "Removing from list."
            )
            log.warn(text)
            dev_msg(text)
            context.dispatcher.user_data[chat_id].clear()
            context.dispatcher.update_persistence()
            remove.append(chat_id)
    if remove:
        for rid in remove:
            context.bot_data["group_association"].get(group, []).remove(rid)


def orga_msg(update: Update, context: CallbackContext, message: str) -> None:
    """Send message to all groups in `orga.json`"""
    from src.config import ORGA_GROUPS

    for group in ORGA_GROUPS:
        group_msg(update, context, group, message)


initial_keyboard = ReplyKeyboardMarkup(
    INITIAL_KEYBOARD, resize_keyboard=True, is_persistent=True
)
main_keyboard = ReplyKeyboardMarkup(
    MAIN_KEYBOARD, resize_keyboard=True, is_persistent=True
)
orga_keyboard = ReplyKeyboardMarkup(
    ORGA_KEYBOARD, resize_keyboard=True, is_persistent=True
)


def autoselect_keyboard(
    update: Update, context: CallbackContext
) -> ReplyKeyboardMarkup:
    """Select keyboard with commands automatically based on group membership."""
    if not context.user_data:
        return initial_keyboard
    if group := context.user_data.get("group_association"):
        if group in ORGA_GROUPS:
            return orga_keyboard
        return main_keyboard
    else:
        return initial_keyboard


def dev_html(
    update: Update,
    context: CallbackContext,
    message: str,
):
    """Send potentially long message to the developer, and have it parsed as HTML."""
    from src.config import DEVELOPER_CHAT_ID

    n = 4096 - 11  # for tags <pre></pre>
    if len(message) > n:
        # need to split messages
        for i in range(0, len(message), n):
            prefix = "<pre>" if i != 0 else ""
            suffix = "</pre>" if i + n < len(message) else ""
            text = prefix + message[i : i + n] + suffix
            context.bot.send_message(
                chat_id=DEVELOPER_CHAT_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=autoselect_keyboard(update, context),
            )
    else:
        # send full message directly
        context.bot.send_message(
            chat_id=DEVELOPER_CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML,
            reply_markup=autoselect_keyboard(update, context),
        )
