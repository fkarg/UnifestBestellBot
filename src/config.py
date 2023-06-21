from pathlib import Path
import json


LOGGING_FORMAT = "%(asctime)s [%(funcName)s]: %(message)s"

ROOT = Path(".")
SECRETS_DIR = ROOT / "unifest-secrets"


def load_json(filename):
    with open(SECRETS_DIR / filename, "r") as f:
        return json.load(f)


TOKEN = load_json("token.json")  # str
GROUPS_LIST = load_json("groups.json")  # [str]
MAPPING = load_json("mapping.json")  # dict: str -> str
UPDATES_CHANNEL_ID = load_json("channel.json")  # int
DEVELOPER_CHAT_ID = load_json("developer.json")  # int
ORGA_GROUPS = load_json("orga.json")  # [str]
HIDDEN_GROUPS = load_json("hidden.json")  # [str]

# If not used, create json file with "{}" as file content
MQTT_HOST = None  # str | None
MQTT_PORT = None  # int | None
MQTT_USER = None  # str | None
MQTT_PASS = None  # str | None

_mqtt = load_json("mqtt.json")
if _mqtt:
    MQTT_HOST = _mqtt["host"]
    MQTT_PORT = _mqtt["port"]
    MQTT_USER = _mqtt["user"]
    MQTT_PASS = _mqtt["pass"]

CONNECT_BROKER = MQTT_HOST and MQTT_PORT and MQTT_USER and MQTT_PASS

ALL_GROUPS = GROUPS_LIST + ORGA_GROUPS + HIDDEN_GROUPS

# options for state machine. You still need to manually adapt regex and
# functions too.
REQUEST_OPTIONS = [["Becher", "Geld", "/cancel"], ["Bier", "Cocktail", "Sonstiges"]]
MONEY_OPTIONS = [
    ["Geld Abholen", "/cancel"],
    ["Wechselgeld", "Freitext"],
]
CUP_OPTIONS = [["Dreckige Abholen", "/cancel"], ["Shotbecher", "Normale Becher"]]
AMOUNT_OPTIONS = [["0", "/cancel"], ["~10", "~20", "~50"]]

INITIAL_KEYBOARD = [["/help", "/register"]]
MAIN_KEYBOARD = [["/help", "/status"], ["/request"]]
ORGA_KEYBOARD = [["/help", "/help2", "/all"], ["/tickets", "/wip", "/close"]]
