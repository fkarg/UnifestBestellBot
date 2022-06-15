import json
import logging


def set_log_level_format(logging_level, format):
    logging.addLevelName(logging_level, format % logging.getLevelName(logging_level))


def get_logging_level(args):
    if args.verbose >= 3:
        return logging.DEBUG
    if args.verbose == 2:
        return logging.INFO
    if args.verbose >= 1:
        return logging.WARNING
    return logging.ERROR


def load_json(filename):
    from lib.config import SECRETS_DIR

    with open(SECRETS_DIR / filename, "r") as f:
        return json.load(f)


def save_json(data, filename):
    from lib.config import SECRETS_DIR

    with open(SECRETS_DIR / filename, "w") as file:
        json.dump(data, file)
