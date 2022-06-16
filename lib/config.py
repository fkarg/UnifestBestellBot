from pathlib import Path
from lib.utils import load_json


# LOGGING_FORMAT= "{asctime} [{funcName}]: {message}"
LOGGING_FORMAT = "%(asctime)s [%(funcName)s]: %(message)s"

ROOT = Path(".")
SECRETS_DIR = ROOT / "unifest-secrets"


TOKEN = load_json("token.json")  # str
GROUPS_LIST = load_json("groups.json")  # [str]
MAPPING = load_json("mapping.json")  # dict: str -> str
UPDATES_CHANNEL_ID = load_json("channel.json")  # int
DEVELOPER_CHAT_ID = load_json("developer.json")  # int

ORGA_GROUPS = ["Festko", "Finanzer", "BiMi"]

# options for state machine. You still need to manually adapt regex and functions too.
REQUEST_OPTIONS = [["Bier", "Cocktail", "Becher", "Geld", "Sonstiges"]]
MONEY_OPTIONS = [
    ["Geld Abholen"],
    ["2€ Münzen", "1€ Münzen", "50ct Münzen"],
    ["20€ Scheine", "10€ Scheine", "5€ Scheine"],
]
CUP_OPTIONS = [["Shotbecher", "Normale Becher", "Dreckige Abholen"]]
