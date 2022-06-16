from telegram import (
    InlineKeyboardButton,
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
from lib.commands import channel_msg, dev_msg, orga_msg, festko_command
from lib.tickets import create_ticket

log = logging.getLogger(__name__)

# define all available states for full state machine
(
    REQUEST,
    MONEY,
    CUPS,
    AMOUNT,
    FREE,
) = range(5)


def end(update: Update, context: CallbackContext) -> int:
    try:
        context.user_data["open_ticket"] = False
        del context.user_data["first_choice"]
        del context.user_data["second_choice"]
    except KeyError:
        pass
    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels and ends the conversation."""
    update.message.reply_text("Cancelled request.", reply_markup=ReplyKeyboardRemove())
    return end(update, context)


def request(update: Update, context: CallbackContext) -> int:
    if context.user_data.get("open_ticket"):
        update.message.reply_text(
            "Your current request is still in progress. Please finish it or /cancel before opening the next one."
        )
        return REQUEST
    else:
        context.user_data["open_ticket"] = True
    if not context.user_data.get("group_association"):
        update.message.reply_text(
            "Please register your group association with /register before requesting supplies."
        )
        return end(update, context)
    update.message.reply_text(
        "Hey! I will guide you through your request. Send /cancel to stop.\n\n"
        "What category does your request fall into?",
        reply_markup=ReplyKeyboardMarkup(
            REQUEST_OPTIONS,
            one_time_keyboard=True,
            input_field_placebo="What to create a ticket about?",
        ),
    )
    return REQUEST


def money(update: Update, context: CallbackContext) -> int:
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


def cups(update: Update, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text

    update.message.reply_text(
        "Do you need cups retrieved (someone will drop by to pick them up) or new ones?",
        reply_markup=ReplyKeyboardMarkup(
            CUP_OPTIONS,
            one_time_keyboard=True,
        ),
    )
    return CUPS


def free_next(update: Update, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text
    update.message.reply_text(
        "Tell me what you need, and how much you have left.",
        reply_markup=ReplyKeyboardRemove(),
    ),
    return FREE


def ask_amount(update: Update, context: CallbackContext) -> int:
    context.user_data["second_choice"] = update.message.text
    update.message.reply_text(
        "How many do you have left?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AMOUNT


def amount(update: Update, context: CallbackContext) -> int:
    try:
        amount = int(update.message.text)
    except ValueError:
        update.message.reply_text("Please enter a valid number.")
        return AMOUNT
    group = context.user_data["group_association"]
    category = context.user_data["first_choice"]
    detailed = context.user_data["second_choice"]
    uid = create_ticket(
        update,
        context,
        group,
        category,
        details=f"They have only {amount} of {detailed} left.",
    )

    channel_msg(f"#{uid}: {group} on {category}: only {amount} of {detailed} left")
    update.message.reply_text(f"Created Ticket #{uid}.")
    return end(update, context)


def collect(update: Update, context: CallbackContext) -> int:
    context.user_data["second_choice"] = update.message.text
    group = context.user_data["group_association"]
    category = context.user_data["first_choice"]
    uid = create_ticket(
        update,
        context,
        group,
        category,
        details="Send someone to collect money.",
    )

    channel_msg(f"#{uid}: {group} requested collection of money")
    update.message.reply_text(f"Created Ticket #{uid} about necessity to collect money.")
    return end(update, context)


def retrieval(update: Update, context: CallbackContext) -> int:
    group = context.user_data["group_association"]
    category = context.user_data["first_choice"]
    uid = create_ticket(
        update,
        context,
        group,
        category,
        details="Send someone to retrieve dirty cups.",
    )

    channel_msg(f"#{uid}: {group} requested retrieval of cups")
    update.message.reply_text(f"Created Ticket #{uid} about necessity to retrieve dirty cups.")
    return end(update, context)


def free(update: Update, context: CallbackContext) -> int:
    """free text field"""
    # for beer and cocktail, and other requests
    log.info(update.message.text)
    group = context.user_data["group_association"]
    category = context.user_data["first_choice"]
    uid = create_ticket(
        update,
        context,
        group,
        category,
        details=update.message.text,
    )

    channel_msg(f"#{uid}: {group} requested {update.message.text} for {category}")
    update.message.reply_text(f"Created ticket #{uid}.")
    #     reply_markup=InlineKeyboardMarkup(
    #         [[InlineKeyboardButton("Update", callback_data=f"update #{uid}")]],
    #     ),
    # )
    return end(update, context)
