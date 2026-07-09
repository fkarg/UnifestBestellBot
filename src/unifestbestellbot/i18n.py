"""All German user-facing strings. Centralized so they're greppable
and stay consistent in tone."""

# --- /start, /help -------------------------------------------------------

START = (
    "Hi, Ich bin der UnifestBestellBot. Über mich können Stände Nachschub "
    "bestellen, insbesondere Kleingeld, Becher, Bier, und Cocktailmaterialien. "
    "Als erstes solltest du deine Gruppenmitgliedschaft mit /register festlegen, "
    "um anschließend mit /request eine Anfrage stellen zu können. "
    "Alle verfügbaren Kommandos und deren Erklärung kannst du mit /help sehen."
)

HELP = """Verfügbare Befehle:
/start
    Zeige initiale Willkommensnachricht an.
/register
    Registriere deine Gruppenmitgliedschaft.
    Muss getan werden, bevor du Anfragen
    stellen kannst.
/unregister
    Entferne deine Gruppenmitgliedschaft.
/name [anzeigename]
    Setze einen eigenen Anzeigenamen
    (statt deines Telegram-Namens).
    Ohne Argument: aktuellen anzeigen,
    /name - setzt zurück.
/status
    Zeige deine Gruppenmitgliedschaft und
    offene Tickets deiner Gruppe an.
/request
    Erstelle eine Anfrage. Mit ein paar
    Fragen kannst du genau bestimmen, was
    ihr braucht.
/cancel
    Breche das Erstellen der momentanen
    Anfrage ab.
/helpers [gruppe]
    Zeige Helfer-Schichten am Standort.
/quiet [minutes]
    Unterdrücke Aktivitätsmeldungen
    deiner Gruppe für eine Anzahl
    Minuten (Standard: 30, Max: 1440).
    Eigene Ticket-Updates kommen weiter.
/loud
    Aktivitätsmeldungen wieder einschalten.
/notify
    Einzelne Benachrichtigungs-Typen
    dauerhaft an-/abschalten.
/bug <text>
    Melde ein Problem an die Bot-Betreiber.
/feature <text>
    Schlage eine Verbesserung vor.
/help
    Zeige diese Hilfenachricht an.
"""

HELP_ORGA = """Zusätzlich verfügbare Kommandos für [ORGA]:
/all
    Zeige die Liste aller offenen Tickets.
/tickets
    Zeige die Liste der offenen Tickets
    für deine Gruppe.
/wip [ticket-id]
    Beginne Arbeit an einem Ticket.
/close [ticket-id]
    Schließe ein Ticket. Ohne ID werden
    zuerst deine eigenen WIP-Tickets
    angezeigt.
/self
    Deine Übersicht: laufende WIP-Tickets
    und wie viele du erledigt hast.
/move <ticket-id> <orga-gruppe>
    Weise ein offenes Ticket einer
    anderen Orga-Gruppe zu.
/message <ticket-id> <text>
    Sende eine Nachricht an die Gruppe,
    die das Ticket erstellt hat.
/helpers
    Zeige Helfer-Schichten am Standort.
/history [n]
    Letzte n geschlossene Tickets deiner
    Gruppe (default 10, max 50) mit wer
    sie geschlossen hat.
/help2
    Zeige diese Hilfenachricht.
"""

# --- Registration --------------------------------------------------------

REGISTER_PROMPT = "Mögliche Gruppen:"
REGISTER_CANCELLED = "Gruppenauswahl abgebrochen."
REGISTER_SUCCESS = "Anmelden bei Gruppe [{group}] erfolgreich."
REGISTER_KEYBOARD_UPDATE = "Tastatur aktualisiert."
UNKNOWN_GROUP = "Unbekannte Gruppe."

UNREGISTER_SUCCESS = "Mitgliedschaft bei Gruppe [{group}] entfernt."
UNREGISTER_NONE = "Keine Gruppenmitgliedschaft registriert. Nichts zu entfernen."

NAME_USAGE = "Benutzung: /name <Anzeigename>. Mit /name - zurücksetzen."
NAME_CURRENT = "Dein Anzeigename: {name}\n\n" + NAME_USAGE
NAME_SET = "Anzeigename gesetzt: {name}"
NAME_CLEARED = "Anzeigename zurückgesetzt. Es gilt wieder dein Telegram-Name."

NOTIFY_HEADER = "🔔 Benachrichtigungen — tippe zum Umschalten:"
NOTIFY_DONE = "Benachrichtigungs-Einstellungen gespeichert."
NOTIFY_DONE_BTN = "✅ Fertig"
NOTIFY_ON = "🔔"
NOTIFY_OFF = "🔕"
NOTIFY_LABEL_OPENED = "Neue Tickets der Gruppe"
NOTIFY_LABEL_WIP = "WIP-Übernahmen von anderen"
NOTIFY_LABEL_CLOSED = "Schließungen von anderen"

QUIET_USAGE = "Benutzung: /quiet [minutes]. Standard 30, Maximum 1440."
QUIET_SET = (
    "🔕 Aktivitätsmeldungen für {minutes} Minute(n) ausgeschaltet. "
    "Eigene Ticket-Updates erhältst du weiter. Mit /loud sofort beenden."
)
LOUD_SET = "🔔 Aktivitätsmeldungen wieder eingeschaltet."
LOUD_ALREADY = "Aktivitätsmeldungen waren nicht ausgeschaltet."

NOT_REGISTERED = (
    "Bitte registriere deine Gruppenmitgliedschaft mit /register, "
    "bevor du Anfragen stellst."
)

# --- /status -------------------------------------------------------------

STATUS_NO_REGISTRATION = "Keine Gruppenmitgliedschaft."
STATUS_WITH_TICKETS = (
    "Mitglied der Gruppe [{group}].\n\n"
    "{group} hat {count} Ticket(s) offen:\n\n{tickets}"
)
STATUS_NO_TICKETS = (
    "Mitglied der Gruppe [{group}].\n\nDeine Gruppe hat gerade keine offenen Tickets."
)

# --- /request flow -------------------------------------------------------

REQUEST_INTRO = (
    "Ein paar Fragen, um deine Anfrage zu präzisieren.\n"
    "Sende /cancel um abzubrechen.\n\n"
    "In welche Kategorie fällt deine Anfrage?"
)
REQUEST_IN_PROGRESS = (
    "Deine momentane Anfrage ist noch nicht abgeschlossen. "
    "Bitte beende diese zuerst oder sende /cancel um abzubrechen."
)
REQUEST_CANCELLED = "Anfrage abgebrochen."
REQUEST_CATEGORY_UNKNOWN = "Bitte wähle eine Option oder /cancel."
REQUEST_TICKET_CREATED = "Ticket #{uid} erstellt. Geht an [{orga}]."

ASK_MONEY = "Braucht ihr Geld abgeholt oder Wechselgeld?"
ASK_MONEY_CHANGE = "Braucht ihr Scheine oder Münzen?"
ASK_CUPS = "Braucht ihr dreckige Becher abgeholt oder neue?"
ASK_AMOUNT = "Wie viel habt ihr noch bzw. braucht ihr?"
ASK_FREE = "Was braucht Ihr, und wie viel habt ihr davon noch?"
ASK_HELPER = (
    "Habt ihr zu viele (langweilen sich), zu wenige "
    "(alle die da sein sollten sind da, aber es reicht nicht), "
    "oder fehlen welche (Schichthelfer sind nicht aufgetaucht)?"
)
ASK_HELPER_FREE = "Wie ist der username der nicht aufgetauchten Helfer?"

# --- Orga / tickets ------------------------------------------------------

ORGA_DENIED = (
    "Dieser Befehl ist dir nicht erlaubt. Mit /status siehst du deine "
    "Gruppenmitgliedschaft und offene Tickets in deiner Gruppe."
)
DEV_DENIED = "Du bist nicht zur Ausführung dieses Kommandos berechtigt."

NO_OPEN_TICKETS_FOR_GROUP = "Keine offenen Tickets für [{group}]."
NO_WIP_TICKETS_FOR_GROUP = "Keine WIP Tickets von [{group}]."
NO_OPEN_TICKETS_ANYWHERE = "Momentan gibt es keine offenen Tickets."
NO_OPEN_TICKETS_FOR_USER_GROUP = "Momentan gibt es keine offenen Tickets für [{group}]."
OPEN_TICKETS_LIST = "Offene Tickets:"
WIP_TICKETS_LIST = "WIP Tickets:"
MY_WIP_TICKETS_LIST = "Deine WIP Tickets:"
NO_OWN_WIP_SHOWING_GROUP = "Keine eigenen WIP Tickets. Alle WIP Tickets von [{group}]:"
TICKETS_FOR_GROUP_HEADER = "Liste der offenen Tickets für [{group}]:\n\n{tickets}"

PICKER_CANCEL = "❌ Abbrechen"
PICKER_CANCELLED = "❌ Abgebrochen."
PICKER_SHOW_ALL = "📋 Alle der Gruppe anzeigen"

TICKET_NOT_FOUND_OR_CLOSED = "Ticket #{uid} wurde bereits geschlossen oder existiert noch nicht."
TICKET_ALREADY_WIP = "Jemand arbeitet bereits daran."
TICKET_WIP_NOTICE = "Ticket #{uid} ist jetzt 🟢 WIP."
TICKET_CLOSED_NOTICE = "Ticket #{uid} ist jetzt ✅ CLOSED."
TICKET_MOVED_NOTICE = "Ticket #{uid} ist jetzt {group} zugewiesen."
TICKET_MOVE_BLOCKED_WIP = "Ticket #{uid} wird bereits bearbeitet und kann daher nicht verschoben werden."

MOVE_USAGE = "Benutzung: /move <ticket-id> <orga-gruppe>. Existierende Gruppen: {groups}"
MESSAGE_USAGE = "Benutzung: /message <ticket-id> <nachricht>"
MESSAGE_DELIVERED = "Nachricht verschickt."

HISTORY_USAGE = "Benutzung: /history [n]. n zwischen 1 und 50."
HISTORY_EMPTY = "Keine geschlossenen Tickets für [{group}]."
HISTORY_HEADER = "Letzte geschlossene Tickets für [{group}]:"

# --- /self (eigene Perspektive) ------------------------------------------

SELF_HEADER = "👤 Deine Übersicht:"
SELF_WIP_LINE = "🟢 Laufende WIP-Tickets: {count}"
SELF_NO_WIP = "(keine laufenden WIP-Tickets)"
SELF_CLOSED_LINE = "✅ Erledigt: {today} heute / {total} gesamt"
SELF_AVG_LINE = "⏱ Ø Bearbeitungszeit: {avg}"
SELF_AVG_NONE = "—"

# --- Engelsystem shift digest --------------------------------------------

DIGEST_NEXT_SHIFT = "🧑‍🔧 Schicht beginnt um {time} an {location}:"
DIGEST_NO_ENTRIES = "  (keine Helfer eingetragen)"

# --- group fanout messages ----------------------------------------------

GROUP_TICKET_OPENED = "🟠 OPEN: {who} in deiner Gruppe hat gerade Ticket '{text}' erstellt."
GROUP_TICKET_FOR_ORGA = "🟠 OPEN #{uid}: {text}"
GROUP_TICKET_WIP_OWNER = "🟢 WIP: Euer Ticket #{uid} wurde angefangen zu bearbeiten."
GROUP_TICKET_WIP_PEER = "{who} arbeitet jetzt an Ticket #{uid}."
GROUP_TICKET_CLOSED_OWNER = "✅ CLOSED: Euer Ticket #{uid} wurde bearbeitet."
GROUP_TICKET_CLOSED_PEER = "✅ CLOSED: {who} hat Ticket #{uid} geschlossen."
GROUP_INCOMING_MESSAGE = "🟣 Nachricht von {sender}: {message}"

# --- Channel log messages (for the updates channel) ----------------------

CH_OPEN = "🟠 OPEN #{uid}: {text}"
CH_WIP = "🟢 WIP: {who} von [{group}] arbeitet jetzt an Ticket #{uid}."
CH_CLOSED = "✅ CLOSED: {who} von [{group}] hat Ticket #{uid} geschlossen."
CH_MOVED = "🟠 MOVED #{uid} to be handled by {group}"
CH_REGISTER = "🔵 {who} registered as member of group {group}."
CH_UNREGISTER = "🔵 {who} unregistered from group {group}."
CH_RENAME = "🔵 {old} von [{group}] heißt jetzt {new}."
CH_MESSAGE = "🟣 Nachricht von {sender} an {recipient}: {message}"
CH_BOT_STARTED = "🔘 Started from {host}"

# --- Bug / feature reports ---------------------------------------------

BUG_USAGE = "Benutzung: /bug <message>"
BUG_FORWARDED = "Fehlerbericht an Entwickler weitergeleitet."
FEATURE_USAGE = "Benutzung: /feature <message>"
FEATURE_FORWARDED = "Feature Request an Entwickler weitergeleitet."

DEV_BUG = "⚪️ Bug report von {who}: {message}"
DEV_FEATURE = "⚪️ feature request von {who}: {message}"

# --- Unknown ------------------------------------------------------------

UNKNOWN_COMMAND = (
    "Kommando nicht erkannt oder im falschen Zusammenhang.\n\n"
    "Sende /help um eine Übersicht zu allen verfügbaren Kommandos zu bekommen."
)
