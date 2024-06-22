import json
import requests
import logging

from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

from src.config import MAPPING, LOCATIONS, ENGELSYSTEM_API_KEY
from src.utils import dev_msg, autoselect_keyboard
from src.states import end

log = logging.getLogger(__name__)

host_url = "https://helfen.unifest-karlsruhe.de/api/v0-beta/"

headers = {
    "Accept": "application/json",
    "x-api-key": ENGELSYSTEM_API_KEY,
}

def helpers(update: Update, context: CallbackContext):
    group = context.user_data.get("group_association")
    if not group:
        update.message.reply_text(
            "Bitte registriere deine Gruppenmitgliedschaft mit /register "
            "bevor du anfragen stellst.",
            reply_markup=autoselect_keyboard(update, context),
        )
        return

    try:
        if context.args:
            group = " ".join(context.args)

        loc = LOCATIONS[MAPPING[group]]

        response = requests.get(host_url + f"locations/{loc}/shifts", headers=headers)

        shifts = json.loads(response.content)
        shifts = shifts['data']

        now = datetime.now(timezone.utc)
        delta = timedelta(minutes=20)

        def is_current(shift):
            shift_start = datetime.fromisoformat(shift['starts_at'])
            shift_end = datetime.fromisoformat(shift['ends_at'])
            return shift_start < now and shift_end > now

        def is_next(shift):
            shift_start = datetime.fromisoformat(shift['starts_at'])
            shift_end = datetime.fromisoformat(shift['ends_at'])
            return shift_start > now and shift_start - delta < now

        shifts_current = [shift for shift in shifts if is_current(shift)]
        shifts_next = [shift for shift in shifts if is_next(shift)]

        message = ""

        for shift in shifts_current:
            delta = datetime.fromisoformat(shift['ends_at']) - now
            message += f"Momentane Schicht noch {delta}:\n"
            for entry in shift['entries']:
                for user in entry['users']:
                    message += f"- {user['name']} [{entry['type']['name']}]\n"
            message += "\n\n"

        for shift in shifts_next:
            delta = datetime.fromisoformat(shift['starts_at']) - now
            message += f"Nächste Schicht in {delta}:\n"
            for entry in shift['entries']:
                for user in entry['users']:
                    message += f"- {user['name']} [{entry['type']['name']}]\n"
            message += "\n\n"

        update.message.reply_text(
            f"{message}",
            reply_markup=autoselect_keyboard(update, context),
        )
        return end(update, context)

    except KeyError:
        update.message.reply_text(
            "Deine Gruppe hat keine Schichten im Engelsystem oder der Standort ist nicht korrekt assoziiert. Wende dich an den Entwckler.",
            reply_markup=autoselect_keyboard(update, context),
        )
        return end(update, context)


