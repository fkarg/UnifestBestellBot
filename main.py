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
    """Main function, setting up bot update->dispatcher->handler structure

    Relevant persistence structures:
    user_data['group_association'] for Group
    bot_data['orga'] for [chat_id] from Festko
    bot_data['group_association'] for dict Group -> [chat_id]
    bot_data['highest'] for int of next highest ticket id
    bot_data['tickets'] for dict id -> (Group, message, is_wip: bool)
    """

    persistence = PicklePersistence(filename="bot_persistence.cntx")
    updater = Updater(token=TOKEN, persistence=persistence)
    dispatcher = updater.dispatcher

    # add various handlers here
    dispatcher.add_handler(CommandHandler("start", start))

    dispatcher.add_handler(
        CallbackQueryHandler(task_button, pattern="^(update|wip|close) #[0-9]+$")
    )
    dispatcher.add_handler(CallbackQueryHandler(register_button))

    # large request handler
    dispatcher.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("request", request)],
            states={
                REQUEST: [
                    MessageHandler(Filters.regex("^Geld$"), money),
                    MessageHandler(Filters.regex("^Becher$"), cups),
                    MessageHandler(Filters.regex("^Sonstiges$"), free_next),
                    MessageHandler(Filters.regex("^(Bier|Cocktail)$"), free_next),
                    CommandHandler("cancel", cancel),
                ],
                MONEY: [
                    MessageHandler(Filters.regex("^Geld Abholen$"), sammeln),
                    MessageHandler(Filters.regex("^(2€|1€|50ct) Münzen$"), ask_amount),
                    MessageHandler(Filters.regex("^(5|10|20)€ Scheine$"), ask_amount),
                    MessageHandler(
                        Filters.regex("^Wechselgeld: (Scheine|Münzen)$"), ask_amount
                    ),
                    CommandHandler("cancel", cancel),
                ],
                CUPS: [
                    MessageHandler(
                        Filters.regex("^(Shotbecher|Normale Becher)$"), ask_amount
                    ),
                    # MessageHandler(Filters.regex("^Normale Becher$"), ask_amount),
                    MessageHandler(Filters.regex("^Dreckige Abholen$"), sammeln),
                    CommandHandler("cancel", cancel),
                ],
                # and three options with free text fields
                # BEER: [free_text],
                # COCKTAIL: [free_text],
                # OTHER: [free_text],
                FREE: [
                    MessageHandler(Filters.text & ~Filters.command, free),
                    CommandHandler("cancel", cancel),
                ],
                AMOUNT: [
                    MessageHandler(Filters.text & ~Filters.command, amount),
                    CommandHandler("cancel", cancel),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel),
                # CommandHandler("abbruch", cancel),
            ],
            name="ticket_requests",
            persistent=True,
        )
    )

    # regular commands
    dispatcher.add_handler(CommandHandler("register", register))
    dispatcher.add_handler(CommandHandler("unregister", unregister))
    dispatcher.add_handler(CommandHandler("reset", reset_user))

    dispatcher.add_handler(CommandHandler("request", request))
    dispatcher.add_handler(CommandHandler("bug", bug))
    dispatcher.add_handler(CommandHandler("help", help))
    dispatcher.add_handler(CommandHandler("status", status))

    # hidden commands (not in help)
    dispatcher.add_handler(CommandHandler("location", location))
    dispatcher.add_handler(CommandHandler("details", details))
    dispatcher.add_handler(CommandHandler("inline", inline))

    # Orga commands
    dispatcher.add_handler(CommandHandler("help2", help2))
    dispatcher.add_handler(CommandHandler("system", system_status))
    dispatcher.add_handler(CommandHandler("tickets", tickets))
    dispatcher.add_handler(CommandHandler("message", message))
    dispatcher.add_handler(CommandHandler("close", close))
    dispatcher.add_handler(CommandHandler("wip", wip))

    # Developer
    # dispatcher.add_handler(CommandHandler("reset", reset))
    dispatcher.add_handler(CommandHandler("closeall", closeall))

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
