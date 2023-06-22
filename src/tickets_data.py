from enum import Enum
import json

from telegram.ext import (
    CallbackContext,
)


def increase_highest_id(context: CallbackContext):
    """ Keep internal counter of 'next' ticket id.
    """
    highest = context.bot_data.get("highest_id", 0)
    context.bot_data["highest_id"] = highest + 1
    return highest


class TicketStatus(Enum):
    """ Define Ticket Status and its different representations
    """
    OPEN = "🟠 OPEN"
    WIP = "🟢 WIP"
    CLOSED = "✅ CLOSED"

    def __repr__(self):
        return "%s.%s" % (self.__class__.__name__, self._name_)

    def __str__(self):
        return self._value_

    def toJSON(self):
        return repr(self)


class Ticket:
    """ Collection of fields and functions directly related to Tickets.
    """
    def __init__(
        self,
        group_requesting: str,
        group_tasked: str,
        text: str,
        context: CallbackContext = None,
        uid: int = None,
        status: TicketStatus = TicketStatus.OPEN,
    ):
        assert uid or context is not None

        if uid:
            self.uid = uid
        else:
            self.uid = increase_highest_id(context)
        self.status = status
        self.group_requesting = group_requesting
        self.group_tasked = group_tasked
        self.text = text
        self.who = ""

    def __repr__(self):
        return (
            f"Ticket(group_requesting='{self.group_requesting}', group_tasked="
            f"'{self.group_tasked}', text='{self.text}', uid={self.uid}, "
            f"who='{self.who}', status={repr(self.status)})"
        )

    def __str__(self):
        return f"{self.status} #{self.uid}: {self.text}"

    def is_open(self) -> bool:
        return self.status == TicketStatus.OPEN

    def is_wip(self) -> bool:
        return self.status == TicketStatus.WIP

    def set_wip(self, who):
        assert self.status == TicketStatus.OPEN
        self.status = TicketStatus.WIP
        self.who = who

    def close(self):
        self.status = TicketStatus.CLOSED

    def is_tasked(self, group: str) -> bool:
        return self.group_tasked == group

    def toJSON(self):
        return repr(self)


class TicketEncoder(json.JSONEncoder):
    """ JSON-Encoder also providing serialization of Ticket and TicketStatus.
    """
    def default(self, obj):
        if isinstance(obj, Ticket):
            return obj.toJSON()
        elif isinstance(obj, TicketStatus):
            return obj.toJSON()
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)