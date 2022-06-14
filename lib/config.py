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
REQUESTS = ["Cups", "Beer", "Cocktail", "Money"]
PRIORITY = ["Critical NOW", "Critical in 5-10min", "Critical soon™"]
ORGA = build_reverse_associations()
