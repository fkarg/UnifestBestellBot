import json
import socket
import logging

import paho.mqtt.client as mqtt

from src.config import MQTT_HOST, MQTT_PASS, MQTT_PORT, MQTT_USER
from src.tickets_data import Ticket, TicketStatus

log = logging.getLogger(__name__)

_client = None
_tickets = {}

def mqtt_set_tickets(tickets: dict):
    global _tickets
    _tickets = tickets

def mqtt_send_all_tickets():
    global _tickets

    for t in _tickets.values():
        dashboard_publish(f"tickets/{t.group_tasked}/{t.uid}", t)

def on_connect(client, userdata, flags, reasonCode, properties=None):
    if not reasonCode == 0:
        return

    mqtt_send_all_tickets()

def dashboard_init():
    log.info("Initializing connection to MQTT broker")
    global _client
    global _tickets
    _client = mqtt.Client(client_id=socket.gethostname(), clean_session=False, transport="websockets")
    _client.username_pw_set(MQTT_USER, MQTT_PASS)
    _client.enable_logger()
    _client.on_connect = on_connect

    # will not fail if no connection can be established but continuously try (re)connecting
    _client.connect_async(MQTT_HOST, MQTT_PORT)

    # broker sends new status on our behalf if we disconnect unexpectedly
    _client.will_set("status", json.dumps({"status": "BOT_CRASHED"}), qos=1, retain=True)


def dashboard_publish(topic: str, message):
    global _client

    if not _client:
        return

    retain = True
    if isinstance(message, Ticket):
        if message.status == TicketStatus.CLOSED or message.status == TicketStatus.REVOKED:
            _client.publish(topic, None, qos=1, retain=True)
            retain = False
        message = {
            "group_requesting": message.group_requesting,
            "group_tasked": message.group_tasked,
            "text": message.text,
            "uid": message.uid,
            "who": message.who,
            "status": message.status.name,
        }
    if not isinstance(message, str):
        message = json.dumps(message, indent=2)
    _client.publish(topic, message, qos=1, retain=retain)

def is_dashboard():
    global _client
    if _client:
        # don't leak the client
        return True
    return False

def dashboard_start():
    global _client

    if not _client:
        return

    _client.loop_start()

def dashboard_stop():
    global _client

    if not _client:
        return

    _client.loop_stop()
    _client.publish("status", json.dumps({"status": "BOT_DISCONNECTED"}), qos=1, retain=True)
    _client.disconnect()