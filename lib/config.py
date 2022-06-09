from pathlib import Path
from lib.utils import load_json


# LOGGING_FORMAT= "{asctime} [{funcName}]: {message}"
LOGGING_FORMAT= "%(asctime)s [%(funcName)s]: %(message)s"

ROOT = Path(".")
SECRETS_DIR = ROOT / "unifest-secrets"


TOKEN = load_json("token.json")
GROUP_ASSOCIATION = load_json("association.json")
GROUPS_LIST = load_json("groups.json")
UPDATES_CHANNEL_ID = load_json("channel.json")
DEVELOPER_CHAT_ID = load_json("developer.json")
