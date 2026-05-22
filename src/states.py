import logging

from src.config import (
    AMOUNT_OPTIONS,
    CUP_OPTIONS,
    HELPER_OPTIONS,
    MAPPING,
    MONEY_CHANGE_OPTIONS,
    MONEY_OPTIONS,
    REQUEST_OPTIONS,
)
from src.tickets import create_ticket
from src.utils import autoselect_keyboard, channel_msg
from telegram import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

log = logging.getLogger(__name__)

# define all available states for full state machine
(
    REQUEST,
    MONEY,
    MONEY_CHANGE,
    CUPS,
    AMOUNT,
    FREE,
    HELPER,
) = range(7)


def end(update: Update, context: CallbackContext) -> int:
    """ End conversation interaction
    """
    try:
        context.user_data["open_ticket"] = False
        del context.user_data["first_choice"]
        del context.user_data["second_choice"]
    except KeyError:
        pass
    return ConversationHandler.END


def reset_user(update: Update, context: CallbackContext) -> int:
    """ Reset local user data. Useful for debugging purposes.
    """
    context.user_data.clear()
    update.message.reply_text(
        "Lokale Benutzerdaten gelöscht, auch deine Gruppenmitgliedschaft. "
        "Du musst dich neu mit /register anmelden.",
        reply_markup=autoselect_keyboard(update, context),
    )
    return end(update, context)


def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels and ends the conversation to create a ticket."""
    update.message.reply_text(
        "Anfrage abgebrochen.", reply_markup=autoselect_keyboard(update, context)
    )
    return end(update, context)


def request(update: Update, context: CallbackContext) -> int:
    """ Begin conversation to open a ticket.
    """
    if context.user_data.get("open_ticket"):
        update.message.reply_text(
            "Deine momentane Anfrage ist noch nicht abgeschlossen. "
            "Bitte beende diese zuerst oder sende /cancel um abzubrechen."
        )
        return REQUEST
    else:
        # user is trying to open a ticket. will be set to False with `end`
        # in case of failure, success, or cancellation.
        context.user_data["open_ticket"] = True

    if not context.user_data.get("group_association"):
        # user is not member of any group.
        update.message.reply_text(
            "Bitte registriere deine Gruppenmitgliedschaft mit /register "
            "bevor du anfragen stellst.",
            reply_markup=autoselect_keyboard(update, context),
        )
        return end(update, context)

    if context.user_data.get("group_association"):
        group = context.user_data.get("group_association")
        if not context.bot_data.get("group_association"):
            # user used to be member of a group, but bot data got reset.
            del context.user_data["group_association"]
            update.message.reply_text(
                "Bitte registriere deine Gruppenmitgliedschaft mit /register "
                "bevor du anfragen stellst.",
                reply_markup=autoselect_keyboard(update, context),
            )
            return end(update, context)
        if update.effective_chat.id not in context.bot_data["group_association"].get(group):
            # user used to be member of a group, but bot data got reset.
            del context.user_data["group_association"]
            update.message.reply_text(
                "Bitte registriere deine Gruppenmitgliedschaft mit /register "
                "bevor du anfragen stellst.",
                reply_markup=autoselect_keyboard(update, context),
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

def money_change(update: Update, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text

    update.message.reply_text(
        "Braucht ihr Scheine oder Münzen?",
        reply_markup=ReplyKeyboardMarkup(
            MONEY_CHANGE_OPTIONS,
        ),
    )
    return MONEY_CHANGE


def cups(update: Update, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text

    update.message.reply_text(
        "Braucht ihr dreckige Becher abgeholt oder neue?",
        reply_markup=ReplyKeyboardMarkup(
            CUP_OPTIONS,
        ),
    )
    return CUPS


def free_next(update: Update, context: CallbackContext) -> int:
    if not context.user_data.get("first_choice"):
       context.user_data["first_choice"] = update.message.text
    update.message.reply_text(
        "Was braucht Ihr, und wie viel habt ihr davon noch?",
        reply_markup=ReplyKeyboardRemove(),
    ),
    return FREE


def ask_amount(update: Update, context: CallbackContext) -> int:
    context.user_data["second_choice"] = update.message.text
    update.message.reply_text(
        "Wie viel habt ihr noch bzw. braucht ihr?",
        reply_markup=ReplyKeyboardMarkup(
            AMOUNT_OPTIONS,
        ),
    )
    return AMOUNT


def amount(update: Update, context: CallbackContext) -> int:
    amount = update.message.text
    group = context.user_data["group_association"]
    location = MAPPING[group]
    category = context.user_data["first_choice"]
    details = context.user_data["second_choice"]
    text = f"{location} [{group}] hat noch {amount} {details}"
    uid = create_ticket(
        update,
        context,
        group,
        text,
        category,
    )

    channel_msg(f"🟠 OPEN #{uid}: {text}")
    update.message.reply_text(
        f"Ticket #{uid} erstellt.", reply_markup=autoselect_keyboard(update, context)
    )
    return end(update, context)


def collect(update: Update, context: CallbackContext) -> int:
    """ Collection of either Money or Cups.
    """
    category = context.user_data["first_choice"]
    group = context.user_data["group_association"]
    location = MAPPING[group]
    text = f"{category} abholen an Stand {location} [{group}]"
    uid = create_ticket(
        update,
        context,
        group,
        text,
        category,
    )

    channel_msg(f"🟠 OPEN #{uid}: {text}")
    update.message.reply_text(
        f"Ticket #{uid} erstellt.",
        reply_markup=autoselect_keyboard(update, context),
    )
    return end(update, context)


def free(update: Update, context: CallbackContext) -> int:
    """Free text field for a number of use cases.
    Specifically, for category `Sonstiges`, as well as to
    specify what is missing in case of Beer and Cocktail.
    """
    # for beer and cocktail, and other requests
    group = context.user_data["group_association"]
    category = context.user_data["first_choice"]
    location = MAPPING[group]
    text = f"{location} [{group}] braucht {category}: '" + update.message.text + "'"
    uid = create_ticket(
        update,
        context,
        group,
        text,
        category,
    )

    channel_msg(f"🟠 OPEN #{uid}: {text}")
    update.message.reply_text(
        f"Ticket #{uid} erstellt.",
        reply_markup=autoselect_keyboard(update, context),
    )
    return end(update, context)

def change(update: Update, context: CallbackContext) -> int:
    group = context.user_data["group_association"]
    category = context.user_data["first_choice"]
    location = MAPPING[group]
    text = f"{location} [{group}] braucht {update.message.text}"
    uid = create_ticket(
        update,
        context,
        group,
        text,
        category,
    )

    channel_msg(f"🟠 OPEN #{uid}: {text}")
    update.message.reply_text(
        f"Ticket #{uid} erstellt.",
        reply_markup=autoselect_keyboard(update, context),
    )
    return end(update, context)


def helper(update: Update, context: CallbackContext) -> int:
    context.user_data["first_choice"] = update.message.text
    update.message.reply_text(
        "Habt ihr zu viele (langweilen sich), zu wenige "
        "(alle die da sein sollten sind da, aber es reicht nicht) "
        " oder fehlen welche (schichthelfer sind nicht aufgetaucht)?",
        reply_markup=ReplyKeyboardMarkup(
            HELPER_OPTIONS,
        ),
    )
    return HELPER


def helper_free_next(update: Update, context: CallbackContext) -> int:
    if not context.user_data.get("first_choice"):
       context.user_data["first_choice"] = update.message.text
    update.message.reply_text(
        "Wie ist der username der nicht aufgetauchten Helfer?",
        reply_markup=ReplyKeyboardRemove(),
    ),
    return FREE
