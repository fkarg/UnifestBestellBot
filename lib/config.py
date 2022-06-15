from pathlib import Path
from lib.utils import load_json, build_reverse_associations


# LOGGING_FORMAT= "{asctime} [{funcName}]: {message}"
LOGGING_FORMAT = "%(asctime)s [%(funcName)s]: %(message)s"

ROOT = Path(".")
SECRETS_DIR = ROOT / "unifest-secrets"


TOKEN = load_json("token.json")  # str
GROUP_ASSOCIATION = load_json("association.json")  # dict: id -> str
GROUPS_LIST = load_json("groups.json")  # [str]
UPDATES_CHANNEL_ID = load_json("channel.json")  # int
DEVELOPER_CHAT_ID = load_json("developer.json")  # int
PRIORITY = ["critical NOW", "critical in 5-10min", "critical soon™"]
ORGA = build_reverse_associations()

# options for state machine. You still need to manually adapt regex and functions too.
REQUEST_OPTIONS = [["Cups", "Beer", "Cocktail", "Money", "Other"]]
MONEY_OPTIONS = [
    ["Collect"],
    ["Coins 2€", "Coins 1€", "Coins 50ct"],
    ["Bills 20€", "Bills 10€", "Bills 5€"],
]
CUP_OPTIONS = [["Shot-glasses", "Normal Cups", "Retrieve dirty"]]
