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
)

from lib.config import *
from lib.utils import *
from lib.commands import *
from lib.states import *
from lib.parser import create_parser


def main(**kwargs):
    # state = load_json(SECRETS_DIR / "state.json")
    # ^ dict with current state of open orders

    updater = Updater(token=TOKEN)
    dispatcher = updater.dispatcher

    # add various handlers here
    dispatcher.add_handler(CommandHandler("start", start))

    dispatcher.add_handler(CommandHandler("inline", inline))
    dispatcher.add_handler(CallbackQueryHandler(button))

    dispatcher.add_handler(ConversationHandler(
        entry_points=[CommandHandler('request', request)],
        states={
            REQUEST: [
                MessageHandler(Filters.regex('^Money$'), money),
                # MessageHandler(Filters.regex('^Cups$'), money),
                # MessageHandler(Filters.regex('^Beer$'), money),
                # MessageHandler(Filters.regex('^Cocktail$'), money),
                # MessageHandler(Filters.regex('^Other$'), other),
                ],
            MONEY: [
                MessageHandler(Filters.regex('^Collect$'), collect),
                # MessageHandler(Filters.regex('^Bills$'), collect),

                ],
            FREE: [MessageHandler(Filters.text & ~Filters.command, free)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    ))
    dispatcher.add_handler(CommandHandler("order", order))
    dispatcher.add_handler(CommandHandler("status", status))
    dispatcher.add_handler(CommandHandler("register", register))
    dispatcher.add_handler(CommandHandler("unregister", unregister))
    dispatcher.add_handler(CommandHandler("request", request))
    dispatcher.add_handler(CommandHandler("reset", reset))
    dispatcher.add_handler(CommandHandler("help", help))

    dispatcher.add_handler(MessageHandler(Filters.command, unknown))
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
