import os
import logging
import socket

from rich.traceback import install

from telegram.ext import (
    Updater,
    Filters,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    PicklePersistence,
)

from src.config import TOKEN
from src.utils import set_log_level_format, get_logging_level, channel_msg
from src.commands import (
    error_handler,
    start,
    help,
    unknown,
    register,
    unregister,
    status,
    details,
    register_button,
    task_button,
    feature,
    bug,
    resetall,
    closeall,
    system_status,
)
from src.states import (
    reset_user,
    cancel,
    request,
    money,
    cups,
    free_next,
    ask_amount,
    amount,
    collect,
    change,
    free,
    REQUEST,
    MONEY,
    CUPS,
    AMOUNT,
    FREE,
)
from src.tickets import close, wip, all, tickets, help2, message
from src.parser import create_parser

# activate tracebacks with `rich` formatting support
install(show_locals=True)


def main(**kwargs):
    """Main function, setting up bot update->dispatcher->handler structure

    Relevant persistence structures:
    user_data['group_association'] for group membership
    bot_data['group_association'] for dict Group -> [chat_id]
    bot_data['highest'] for int of next highest ticket id
    bot_data['tickets'] for dict id -> src.tickets.Ticket
    """

    # configure persistance
    persistence = PicklePersistence(filename="bot_persistence.cntx")
    updater = Updater(token=TOKEN, persistence=persistence)
    dispatcher = updater.dispatcher

    # add various handlers here
    dispatcher.add_handler(CommandHandler("start", start))

    dispatcher.add_handler(
        CallbackQueryHandler(task_button, pattern="^(cancel|wip|close) #[0-9]+$")
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
                    MessageHandler(Filters.regex("^Geld Abholen$"), collect),
                    MessageHandler(Filters.regex("^Freitext$"), free_next),
                    MessageHandler(Filters.regex("^Wechselgeld$"), change),
                    CommandHandler("cancel", cancel),
                ],
                CUPS: [
                    MessageHandler(
                        Filters.regex("^(Shotbecher|Normale Becher)$"), ask_amount
                    ),
                    MessageHandler(Filters.regex("^Normale Becher$"), ask_amount),
                    MessageHandler(Filters.regex("^Dreckige Abholen$"), collect),
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
            ],
            name="ticket_requests",
            persistent=True,
        )
    )

    # regular commands for users
    dispatcher.add_handler(CommandHandler("register", register))
    dispatcher.add_handler(CommandHandler("unregister", unregister))

    dispatcher.add_handler(CommandHandler("request", request))
    dispatcher.add_handler(CommandHandler("bug", bug))
    dispatcher.add_handler(CommandHandler("feature", feature))
    dispatcher.add_handler(CommandHandler("help", help))
    dispatcher.add_handler(CommandHandler("status", status))

    # hidden commands
    # potentially helpful for debugging problems (not in help)
    dispatcher.add_handler(CommandHandler("details", details))
    dispatcher.add_handler(CommandHandler("reset", reset_user))

    # Orga commands
    # only available for groups in ORGA_GROUPS
    dispatcher.add_handler(CommandHandler("help2", help2))
    dispatcher.add_handler(CommandHandler("system", system_status))
    dispatcher.add_handler(CommandHandler("all", all))
    dispatcher.add_handler(CommandHandler("tickets", tickets))
    dispatcher.add_handler(CommandHandler("message", message))
    dispatcher.add_handler(CommandHandler("close", close))
    dispatcher.add_handler(CommandHandler("wip", wip))

    # Developer commands
    # only available from DEVELOPER_CHAT_ID
    dispatcher.add_handler(CommandHandler("resetall", resetall))
    dispatcher.add_handler(CommandHandler("closeall", closeall))

    # register handlers for unknown commands and errors
    dispatcher.add_handler(MessageHandler(Filters.command, unknown))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, unknown))
    dispatcher.add_error_handler(error_handler)

    # Startup message
    channel_msg(f"🔘 Started from {socket.gethostname()}")

    # Begin action loop
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
