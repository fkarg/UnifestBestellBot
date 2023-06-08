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


from src.config import *
from src.utils import channel_msg, dev_msg, orga_msg
from src.commands import festko_command
from src.tickets import create_ticket

import logging

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


def reset_user(update: Update, context: CallbackContext) -> int:
    context.user_data.clear()
    update.message.reply_text(
        "Lokale Benutzerdaten gelöscht, auch deine Gruppenmitgliedschaft. Du musst dich neu mit /register anmelden.",
        reply_markup=ReplyKeyboardRemove(),
    )


def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels and ends the conversation."""
    update.message.reply_text(
        "Anfrage abgebrochen.", reply_markup=ReplyKeyboardRemove()
    )
    return end(update, context)


def request(update: Update, context: CallbackContext) -> int:
    if context.user_data.get("open_ticket"):
        update.message.reply_text(
            # "Your current request is still in progress. Please finish it or /cancel before opening the next one."
            "Deine momentane Anfrage ist noch nicht abgeschlossen. Bitte beende diese zuerst oder sende /cancel um abzubrechen."
        )
        return REQUEST
    else:
        context.user_data["open_ticket"] = True
    if not context.user_data.get("group_association"):
        update.message.reply_text(
            "Bitte registriere deine Gruppenmitgliedschaft mit /register bevor du anfragen stellst."
        )
        return end(update, context)
    if context.user_data.get("group_association"):
        group = context.user_data.get("group_association")
        if not update.effective_chat.id in context.bot_data["group_association"][group]:
            update.message.reply_text(
                # "Please register your group association with /register before requesting supplies."
                "Bitte registriere deine Gruppenmitgliedschaft mit /register bevor du anfragen stellst."
            )
            return end(update, context)
    update.message.reply_text(
        "Ein paar Fragen, um deine Anfrage zu präzisieren.\n"
        "Sende /cancel um abzubrechen.\n\n"
        "In welche Kategorie fällt deine Anfrage?",
        reply_markup=ReplyKeyboardMarkup(
            REQUEST_OPTIONS,
        ),
    )
    return REQUEST


def money(update: Update, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text

    update.message.reply_text(
        "Braucht ihr Geld abgeholt oder Wechselgeld?",
        reply_markup=ReplyKeyboardMarkup(
            MONEY_OPTIONS,
        ),
    )
    return MONEY


def cups(update: Update, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text

    update.message.reply_text(
        "Braucht ihr dreckige Becher abgeholt oder neue?",
        reply_markup=ReplyKeyboardMarkup(
            CUP_OPTIONS,
        ),
    )
    return CUPS


def change(update: Update, context: CallbackContext) -> int:
    # requires change in either Coins or Bills, without further specification
    pass


def free_next(update: Update, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text
    update.message.reply_text(
        "Was braucht Ihr, und wie viel habt ihr davon noch?",
        reply_markup=ReplyKeyboardRemove(),
    ),
    return FREE


def ask_amount(update: Update, context: CallbackContext) -> int:
    context.user_data["second_choice"] = update.message.text
    update.message.reply_text(
        "Wie viel habt ihr noch?",
        reply_markup=ReplyKeyboardMarkup(
            AMOUNT_OPTIONS,
        ),
    )
    return AMOUNT


def amount(update: Update, context: CallbackContext) -> int:
    # try:
    #     amount = int(update.message.text)
    # except ValueError:
    #     update.message.reply_text("Please enter a valid number.")
    #     return AMOUNT
    amount = update.message.text
    group = context.user_data["group_association"]
    location = MAPPING[group]
    category = context.user_data["first_choice"]
    details = context.user_data["second_choice"]
    text = f"{location} hat noch {amount} {details}"
    uid = create_ticket(
        update,
        context,
        group,
        text,
        category,
    )

    channel_msg(f"#{uid}: {text}")
    update.message.reply_text(
        f"Ticket #{uid} erstellt.", reply_markup=ReplyKeyboardRemove()
    )
    return end(update, context)


def collect(update: Update, context: CallbackContext) -> int:
    # inactive
    context.user_data["second_choice"] = update.message.text
    group = context.user_data["group_association"]
    uid = create_ticket(
        update,
        context,
        group,
        "Send someone to collect money.",
    )

    channel_msg(f"#{uid}: {group} requested collection of money")
    update.message.reply_text(
        f"Created Ticket #{uid} about necessity to collect money."
    )
    return end(update, context)


def retrieval(update: Update, context: CallbackContext) -> int:
    # inactive
    group = context.user_data["group_association"]
    category = context.user_data["first_choice"]
    uid = create_ticket(
        update, context, group, "Send someone to retrieve dirty cups.", category
    )

    channel_msg(f"#{uid}: {group} requested retrieval of cups")
    update.message.reply_text(
        f"Created Ticket #{uid} about necessity to retrieve dirty cups."
    )
    return end(update, context)


def sammeln(update: Update, context: CallbackContext) -> int:
    category = context.user_data["first_choice"]
    group = context.user_data["group_association"]
    location = MAPPING[group]
    text = f"{category} abholen an Stand {location}"
    uid = create_ticket(
        update,
        context,
        group,
        text,
        category,
    )

    channel_msg(f"#{uid}: {text}")
    update.message.reply_text(
        f"Ticket #{uid} erstellt.", reply_markup=ReplyKeyboardRemove()
    )
    return end(update, context)


def free(update: Update, context: CallbackContext) -> int:
    """free text field"""
    # for beer and cocktail, and other requests
    group = context.user_data["group_association"]
    category = context.user_data["first_choice"]
    location = MAPPING[group]
    text = f"{location} braucht {category}: '" + update.message.text + "'"
    uid = create_ticket(
        update,
        context,
        group,
        text,
        category,
    )

    channel_msg(f"#{uid}: {text}")
    update.message.reply_text(
        f"Ticket #{uid} erstellt.", reply_markup=ReplyKeyboardRemove()
    )
    #     reply_markup=InlineKeyboardMarkup(
    #         [[InlineKeyboardButton("Update", callback_data=f"update #{uid}")]],
    #     ),
    # )
    return end(update, context)
