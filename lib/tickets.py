from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CallbackContext,
)

from lib.config import MAPPING

# from lib.commands import channel_msg, dev_msg, orga_msg, festko_command

import logging

log = logging.getLogger(__name__)


def increase_highest_id(context: CallbackContext):
    highest = context.bot_data.get("highest_id", 0)
    context.bot_data["highest_id"] = highest + 1
    return highest


class Ticket:
    """Tickets should contain the following information:
    - id
    - status: Open/Closed
    - group requesting
    - what (choice 1)
    - what exactly (choice 2)
    - how much they still have

    Saved in context.bot_data['tickets'][id]
    """

    uid: int = None  # 'highest' lives in bot_data['highest_id']
    open: bool = True  # tickets are open when created initially
    group: str = None  # which group created the ticket
    choice1: str = None  # what has been selected for choice 1
    choice2: str = None  # what has been selected for choice 2
    amount: int = None  # which amount is still left
    free_text: str = None  # text of free text field

    def __init__(self, context: CallbackContext):
        self.uid = increase_highest_id(context)

    @staticmethod
    def create(*args, **kwargs):
        return Ticket(*args, **kwargs)


def add_ticket(context, uid, group, message):
    tickets = context.bot_data.get("tickets")
    if not tickets:
        context.bot_data["tickets"] = {}
    context.bot_data["tickets"][uid] = (group, message, False)


def create_ticket(
    update: Update, context: CallbackContext, group, category, details
) -> None:
    location = MAPPING[group]
    uid = increase_highest_id(context)

    text = f"#{uid}: Group {group} with location {location} requested someone for {category}\n\nDetails: {details}"
    add_ticket(context, uid, group, text)

    keyboard = [
        [InlineKeyboardButton("Update", callback_data=f"update #{uid}")],
        [InlineKeyboardButton("Working on it", callback_data=f"wip #{uid}")],
        [InlineKeyboardButton("Close", callback_data=f"close #{uid}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    log.info(f"new ticket {text}")
    for chat_id in context.bot_data["group_association"]["Festko"]:
        context.bot.send_message(
            chat_id=chat_id, text="Open: " + text,  # reply_markup=reply_markup
        )
    for chat_id in context.bot_data["group_association"][group]:
        if chat_id == update.effective_chat.id:
            continue
        context.bot.send_message(
            chat_id=chat_id,
            text=f"Someone in your group just created ticket #{uid} about {category}\n\n{details}",
            # reply_markup=InlineKeyboardMarkup(
            #     [[InlineKeyboardButton("Update", callback_data=f"update #{uid}")]],
            # ),
        )
    return uid


#
# @festko_command
# def tickets(update: Update, context: CallbackContext) -> None:
#     update.message.reply_text(f"{context.bot_data}")
#
#
# @festko_command
# def close(update: Update, context: CallbackContext) -> None:
#     update.message.reply_text(f"{context.bot_data}")
