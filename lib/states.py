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
) = range(15)


def cancel(update: object, context: CallbackContext) -> int:
    """Cancels and ends the conversation."""
    # TODO: Remove created part of state
    update.message.reply_text("Cancelled request.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def request(update: object, context: CallbackContext) -> int:
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
    # TODO: save decision state ... or do I need to?
    log.info(update.message.text)

    update.message.reply_text(
        "Do you need money collected (someone will drop by to pick it up) or additional change?",
        reply_markup=ReplyKeyboardMarkup(
            MONEY_OPTIONS,
            one_time_keyboard=True,
            input_field_placebo="What is it about?",
        ),
    )

    # TODO: depending on message, branch to other state
    return MONEY

def collect(update: object, context: CallbackContext) -> int:
    # TODO: save decision state of
    log.info(update.message.text)
    log.info("Sending someone to collect Money")
    update.message.reply_text(
        "Sending someone to collect Money.",
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END

def free(update: object, context: CallbackContext) -> int:
    """free text field"""
    # for beer and cocktail, and other requests
    log.info(update.message.text)
    update.message.reply_text(
        "Thank you, your ticket has been created.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END
