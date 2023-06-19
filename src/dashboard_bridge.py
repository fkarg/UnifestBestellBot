import json
import socket

import paho.mqtt.client as mqtt

from src.config import MQTT_HOST
from src.tickets_data import Ticket, TicketStatus

_client = None

def dashboard_init(clear_broker):
    global _client
    _client = mqtt.Client(client_id=socket.gethostname(), clean_session=False)
    _client.connect(MQTT_HOST)

    # broker sends new status on our behalf if we disconnect unexpectedly
    _client.will_set("status", json.dumps({"status": "BOT_CRASHED"}), qos=1, retain=True)

def dashboard_publish(topic: str, message):
    global _client

    retain = True
    if isinstance(message, Ticket):
        if message.status == TicketStatus.CLOSED:
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

def dashboard_start():
    global _client
    _client.loop_start()

def dashboard_stop():
    global _client
    _client.loop_stop()
    _client.publish("status", json.dumps({"status": "BOT_DISCONNECTED"}), qos=1, retain=True)
    _client.disconnect()