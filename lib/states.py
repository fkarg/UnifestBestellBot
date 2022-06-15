from telegram import (
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    Bot,
)
from telegram.ext import (
    Updater,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    CallbackContext,
    ConversationHandler,
)

import logging

from lib.config import *

log = logging.getLogger(__name__)

# define all available states for full state machine
(
    REQUEST,
    MONEY,
    CUPS,
    BEER,
    COCKTAIL,
    OTHER,
    COLLECT,
    BILLS,
    AMOUNT,
    COIN2,
    COIN1,
    COIN0,
    SHOT,
    NORMAL,
    RETRIEVAL,
    FREE,
) = range(16)


def end(update: object, context: CallbackContext) -> int:
    try:
        context.user_data["open_ticket"] = False
        del context.user_data["first_choice"]
    except KeyError:
        pass
    return ConversationHandler.END


def cancel(update: object, context: CallbackContext) -> int:
    """Cancels and ends the conversation."""
    # TODO: Remove created part of state
    update.message.reply_text("Cancelled request.", reply_markup=ReplyKeyboardRemove())
    return end(update, context)


def request(update: object, context: CallbackContext) -> int:
    context.user_data["open_ticket"] = True
    if not context.user_data.get("group_association"):
        update.message.reply_text(
            "Hey, please register your group association with /register before requesting supplies."
        )
        return end(update, context)
    update.message.reply_text(
        "Hey! I will guide you through your request. Send /cancel to stop.\n\n"
        "First, answer me the Following: What category does your request fall into?",
        reply_markup=ReplyKeyboardMarkup(
            REQUEST_OPTIONS,
            one_time_keyboard=True,
            input_field_placebo="What to create a ticket about?",
        ),
    )

    return REQUEST


def money(update: object, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text

    update.message.reply_text(
        "Do you need money collected (someone will drop by to pick it up) or additional change?",
        reply_markup=ReplyKeyboardMarkup(
            MONEY_OPTIONS,
            one_time_keyboard=True,
            input_field_placebo="What is it about?",
        ),
    )
    return MONEY


def cups(update: object, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text

    update.message.reply_text(
        "Do you need money collected (someone will drop by to pick it up) or additional change?",
        reply_markup=ReplyKeyboardMarkup(
            CUP_OPTIONS,
            one_time_keyboard=True,
        ),
    )
    return CUPS


def free_next(update: object, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text
    update.message.reply_text(
        "Tell me what you need, and how much you have left.",
        reply_markup=ReplyKeyboardRemove(),
    ),
    return FREE


def collect(update: object, context: CallbackContext) -> int:
    # TODO: save decision state of
    log.info("Sending someone to collect Money")
    update.message.reply_text(
        "Sending someone to collect Money.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return end(update, context)


def bills(update: object, context: CallbackContext) -> int:
    context.user_data["second_choice"] = update.message.text
    update.message.reply_text(
        "How many do you have left?",
        reply_markup=ReplyKeyboardRemove(),
    ),
    return AMOUNT


def coins(update: object, context: CallbackContext) -> int:
    context.user_data["second_choice"] = update.message.text
    update.message.reply_text(
        "How many do you have left?",
        reply_markup=ReplyKeyboardRemove(),
    ),
    return AMOUNT


def coin2(update: object, context: CallbackContext) -> int:
    return AMOUNT


def coin1(update: object, context: CallbackContext) -> int:
    return AMOUNT


def coin0(update: object, context: CallbackContext) -> int:
    return AMOUNT


def shot(update: object, context: CallbackContext) -> int:
    return AMOUNT


def normal(update: object, context: CallbackContext) -> int:
    return AMOUNT


def retrieval(update: object, context: CallbackContext) -> int:
    return end(update, context)


def amount(update: object, context: CallbackContext) -> int:
    return end(update, context)


def free(update: object, context: CallbackContext) -> int:
    """free text field"""
    # for beer and cocktail, and other requests
    log.info(update.message.text)
    update.message.reply_text(
        "Thank you, your ticket has been created.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return end(update, context)
