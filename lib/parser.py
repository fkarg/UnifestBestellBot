import argparse

def create_parser():

    parser = argparse.ArgumentParser(
        description="",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--nocolor", action="store_true", help="deactivate colored log output"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="make logging output (more) verbose. Default (or 0) is ERROR, -v is WARN, -vv is INFO and -vvv is DEBUG. Can be passed multiple times.",
    )

    return parser
