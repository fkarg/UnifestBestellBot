import os
import logging
import telegram
import argparse

from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    PicklePersistence,
)

from lib.config import *
from lib.utils import *
from lib.commands import *
from lib.states import *
from lib.tickets import *
from lib.parser import create_parser


def main(**kwargs):
    # state = load_json(SECRETS_DIR / "state.json")
    # ^ dict with current state of open orders

    persistence = PicklePersistence(filename="bot_persistence.cntx")
    updater = Updater(token=TOKEN, persistence=persistence)
    dispatcher = updater.dispatcher

    # add various handlers here
    dispatcher.add_handler(CommandHandler("start", start))

    dispatcher.add_handler(CommandHandler("inline", inline))
    dispatcher.add_handler(CallbackQueryHandler(button))

    dispatcher.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("request", request)],
            states={
                REQUEST: [
                    MessageHandler(Filters.regex("^Money$"), money),
                    MessageHandler(Filters.regex("^Cups$"), cups),
                    MessageHandler(Filters.regex("^(Beer|Cocktail|Other)$"), free_next),
                ],
                MONEY: [
                    MessageHandler(Filters.regex("^Collect$"), collect),
                    MessageHandler(Filters.regex("^Bills (5|10|20)€$"), ask_amount),
                    MessageHandler(Filters.regex("^Coins (2€|1€|50ct)$"), ask_amount),
                ],
                CUPS: [
                    MessageHandler(Filters.regex("^Shot-glasses$"), ask_amount),
                    MessageHandler(Filters.regex("^Normal Cups$"), ask_amount),
                    MessageHandler(Filters.regex("^Retrieve dirty$"), retrieval),
                ],
                # and three options with free text fields
                # BEER: [free_text],
                # COCKTAIL: [free_text],
                # OTHER: [free_text],
                FREE: [MessageHandler(Filters.text & ~Filters.command, free)],
                AMOUNT: [MessageHandler(Filters.text & ~Filters.command, amount)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            name="ticket_requests",
            persistent=True,
        )
    )
    dispatcher.add_handler(CommandHandler("status", status))
    dispatcher.add_handler(CommandHandler("details", details))
    dispatcher.add_handler(CommandHandler("register", register))
    dispatcher.add_handler(CommandHandler("unregister", unregister))
    dispatcher.add_handler(CommandHandler("request", request))
    dispatcher.add_handler(CommandHandler("bug", bug))
    dispatcher.add_handler(CommandHandler("help", help))

    # FestKo commands
    dispatcher.add_handler(CommandHandler("help2", help2))
    dispatcher.add_handler(CommandHandler("reset", reset))
    dispatcher.add_handler(CommandHandler("system", system_status))
    # dispatcher.add_handler(CommandHandler("tickets", tickets))
    # dispatcher.add_handler(CommandHandler("close", close))

    dispatcher.add_handler(MessageHandler(Filters.command, unknown))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, unknown))
    dispatcher.add_error_handler(error_handler)

    # begin action loop
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    args = create_parser().parse_args()

    loglevels = [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    ]

    logformats = [
        "\33[0;37m%-8s\033[1;0m",  # DEBUG
        "\33[1;32m%-8s\033[1;0m",  # INFO
        "\33[1;33m%-8s\033[1;0m",  # WARNING
        "\33[1;31m%-8s\033[1;0m",  # ERROR
        "\33[1;41m%-8s\033[1;0m",  # CRITICAL
    ]
    loggingformats = list(zip(loglevels, logformats))

    # check if the terminal supports colored output
    colors = os.popen("tput colors 2> /dev/null").read()
    if colors and int(colors) < 8 or args.nocolor:
        # do not show colors, either not enough are supported or they are not
        # wanted
        nocolor = True
        for level, _format in loggingformats:
            set_log_level_format(level, "%-8s")
    else:
        nocolor = False
        for level, format in loggingformats:
            set_log_level_format(level, format)

    logging.basicConfig(level=get_logging_level(args))  # , format=LOGGING_FORMAT)
    log = logging.getLogger(__name__)
    log.info("Executing as main")
    log.debug("Using terminal color output: %r" % (not nocolor))

    main(**vars(args))
