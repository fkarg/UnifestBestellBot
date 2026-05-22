//! Every German user-facing string. Ported verbatim from
//! `src/unifestbestellbot/i18n.py` so volunteer muscle memory is
//! preserved between implementations. Functions accept owned `String`
//! for ease of use in handlers.

// --- /start, /help -------------------------------------------------------

pub const START: &str = concat!(
    "Hi, Ich bin der UnifestBestellBot. Über mich können Stände Nachschub ",
    "bestellen, insbesondere Kleingeld, Becher, Bier, und Cocktailmaterialien. ",
    "Als erstes solltest du deine Gruppenmitgliedschaft mit /register festlegen, ",
    "um anschließend mit /request eine Anfrage stellen zu können. ",
    "Alle verfügbaren Kommandos und deren Erklärung kannst du mit /help sehen."
);

pub const HELP: &str = "Verfügbare Befehle:
/start
    Zeige initiale Willkommensnachricht an.
/register
    Registriere deine Gruppenmitgliedschaft.
    Muss getan werden, bevor du Anfragen
    stellen kannst.
/unregister
    Entferne deine Gruppenmitgliedschaft.
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
/quiet [minutes]
    Unterdrücke Aktivitätsmeldungen
    deiner Gruppe für eine Anzahl
    Minuten (Standard: 30, Max: 1440).
    Eigene Ticket-Updates kommen weiter.
/loud
    Aktivitätsmeldungen wieder einschalten.
/help
    Zeige diese Hilfenachricht an.
";

pub const HELP_ORGA: &str = "Zusätzlich verfügbare Kommandos für [ORGA]:
/all
    Zeige die Liste aller offenen Tickets.
/tickets
    Zeige die Liste der offenen Tickets
    für deine Gruppe.
/wip [ticket-id]
    Beginne Arbeit an einem Ticket.
/close [ticket-id]
    Schließe ein Ticket.
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
";

// --- Registration --------------------------------------------------------

pub const REGISTER_PROMPT: &str = "Mögliche Gruppen:";
pub const REGISTER_CANCELLED: &str = "Gruppenauswahl abgebrochen.";
pub const REGISTER_KEYBOARD_UPDATE: &str = "Tastatur aktualisiert.";
pub const UNKNOWN_GROUP: &str = "Unbekannte Gruppe.";
pub const UNREGISTER_NONE: &str =
    "Keine Gruppenmitgliedschaft registriert. Nichts zu entfernen.";

pub fn register_success(group: &str) -> String {
    format!("Anmelden bei Gruppe [{}] erfolgreich.", group)
}

pub fn unregister_success(group: &str) -> String {
    format!("Mitgliedschaft bei Gruppe [{}] entfernt.", group)
}

pub const NOT_REGISTERED: &str =
    "Bitte registriere deine Gruppenmitgliedschaft mit /register, bevor du Anfragen stellst.";

// --- /quiet, /loud -------------------------------------------------------

pub const QUIET_USAGE: &str = "Benutzung: /quiet [minutes]. Standard 30, Maximum 1440.";
pub const LOUD_SET: &str = "🔔 Aktivitätsmeldungen wieder eingeschaltet.";
pub const LOUD_ALREADY: &str = "Aktivitätsmeldungen waren nicht ausgeschaltet.";

pub fn quiet_set(minutes: u32) -> String {
    format!(
        "🔕 Aktivitätsmeldungen für {} Minute(n) ausgeschaltet. \
         Eigene Ticket-Updates erhältst du weiter. Mit /loud sofort beenden.",
        minutes
    )
}

// --- /status -------------------------------------------------------------

pub const STATUS_NO_REGISTRATION: &str = "Keine Gruppenmitgliedschaft.";

pub fn status_with_tickets(group: &str, count: usize, tickets: &str) -> String {
    format!(
        "Mitglied der Gruppe [{}].\n\n{} hat {} Ticket(s) offen:\n\n{}",
        group, group, count, tickets
    )
}

pub fn status_no_tickets(group: &str) -> String {
    format!(
        "Mitglied der Gruppe [{}].\n\nDeine Gruppe hat gerade keine offenen Tickets.",
        group
    )
}

// --- /request flow -------------------------------------------------------

pub const REQUEST_INTRO: &str =
    "Ein paar Fragen, um deine Anfrage zu präzisieren.\n\
     Sende /cancel um abzubrechen.\n\n\
     In welche Kategorie fällt deine Anfrage?";
pub const REQUEST_IN_PROGRESS: &str =
    "Deine momentane Anfrage ist noch nicht abgeschlossen. \
     Bitte beende diese zuerst oder sende /cancel um abzubrechen.";
pub const REQUEST_CANCELLED: &str = "Anfrage abgebrochen.";
pub const REQUEST_CATEGORY_UNKNOWN: &str = "Bitte wähle eine Option oder /cancel.";

pub fn request_ticket_created(uid: i64, orga: &str) -> String {
    format!("Ticket #{} erstellt. Geht an [{}].", uid, orga)
}

pub const ASK_MONEY: &str = "Braucht ihr Geld abgeholt oder Wechselgeld?";
pub const ASK_MONEY_CHANGE: &str = "Braucht ihr Scheine oder Münzen?";
pub const ASK_CUPS: &str = "Braucht ihr dreckige Becher abgeholt oder neue?";
pub const ASK_AMOUNT: &str = "Wie viel habt ihr noch bzw. braucht ihr?";
pub const ASK_FREE: &str = "Was braucht Ihr, und wie viel habt ihr davon noch?";
pub const ASK_HELPER: &str =
    "Habt ihr zu viele (langweilen sich), zu wenige (alle die da sein sollten sind da, aber es reicht nicht), \
     oder fehlen welche (Schichthelfer sind nicht aufgetaucht)?";
pub const ASK_HELPER_FREE: &str = "Wie ist der username der nicht aufgetauchten Helfer?";

// --- Orga / tickets ------------------------------------------------------

pub const ORGA_DENIED: &str =
    "Dieser Befehl ist dir nicht erlaubt. Mit /status siehst du deine \
     Gruppenmitgliedschaft und offene Tickets in deiner Gruppe.";
pub const DEV_DENIED: &str = "Du bist nicht zur Ausführung dieses Kommandos berechtigt.";

pub fn no_open_tickets_for_group(group: &str) -> String {
    format!("Keine offenen Tickets für [{}].", group)
}

pub fn no_wip_tickets_for_group(group: &str) -> String {
    format!("Keine WIP Tickets von [{}].", group)
}

pub const NO_OPEN_TICKETS_ANYWHERE: &str = "Momentan gibt es keine offenen Tickets.";

pub fn no_open_tickets_for_user_group(group: &str) -> String {
    format!("Momentan gibt es keine offenen Tickets für [{}].", group)
}

pub const OPEN_TICKETS_LIST: &str = "Offene Tickets:";
pub const WIP_TICKETS_LIST: &str = "WIP Tickets:";

pub fn tickets_for_group_header(group: &str, body: &str) -> String {
    format!("Liste der offenen Tickets für [{}]:\n\n{}", group, body)
}

pub const PICKER_CANCEL: &str = "❌ Abbrechen";
pub const PICKER_CANCELLED: &str = "❌ Abgebrochen.";

pub fn ticket_not_found_or_closed(uid: i64) -> String {
    format!(
        "Ticket #{} wurde bereits geschlossen oder existiert noch nicht.",
        uid
    )
}

pub const TICKET_ALREADY_WIP: &str = "Jemand arbeitet bereits daran.";

pub fn ticket_wip_notice(uid: i64) -> String {
    format!("Ticket #{} ist jetzt 🟢 WIP.", uid)
}

pub fn ticket_closed_notice(uid: i64) -> String {
    format!("Ticket #{} ist jetzt ✅ CLOSED.", uid)
}

pub fn ticket_moved_notice(uid: i64, group: &str) -> String {
    format!("Ticket #{} ist jetzt {} zugewiesen.", uid, group)
}

pub fn ticket_move_blocked_wip(uid: i64) -> String {
    format!(
        "Ticket #{} wird bereits bearbeitet und kann daher nicht verschoben werden.",
        uid
    )
}

pub fn move_usage(orga: &[&str]) -> String {
    format!(
        "Benutzung: /move <ticket-id> <orga-gruppe>. Existierende Gruppen: {:?}",
        orga
    )
}

pub const MESSAGE_USAGE: &str = "Benutzung: /message <ticket-id> <nachricht>";
pub const MESSAGE_DELIVERED: &str = "Nachricht verschickt.";

pub const HISTORY_USAGE: &str = "Benutzung: /history [n]. n zwischen 1 und 50.";
pub fn history_empty(group: &str) -> String {
    format!("Keine geschlossenen Tickets für [{}].", group)
}
pub fn history_header(group: &str) -> String {
    format!("Letzte geschlossene Tickets für [{}]:", group)
}

// --- Group fanout messages ----------------------------------------------

pub fn group_ticket_opened(who: &str, text: &str) -> String {
    format!(
        "🟠 OPEN: {} in deiner Gruppe hat gerade Ticket '{}' erstellt.",
        who, text
    )
}

pub fn group_ticket_for_orga(uid: i64, text: &str) -> String {
    format!("🟠 OPEN #{}: {}", uid, text)
}

pub fn group_ticket_wip_owner(uid: i64) -> String {
    format!("🟢 WIP: Euer Ticket #{} wurde angefangen zu bearbeiten.", uid)
}

pub fn group_ticket_wip_peer(who: &str, uid: i64) -> String {
    format!("{} arbeitet jetzt an Ticket #{}.", who, uid)
}

pub fn group_ticket_closed_owner(uid: i64) -> String {
    format!("✅ CLOSED: Euer Ticket #{} wurde bearbeitet.", uid)
}

pub fn group_ticket_closed_peer(who: &str, uid: i64) -> String {
    format!("✅ CLOSED: {} hat Ticket #{} geschlossen.", who, uid)
}

pub fn group_incoming_message(sender: &str, message: &str) -> String {
    format!("🟣 Nachricht von {}: {}", sender, message)
}

// --- Channel log lines (for the updates channel) -------------------------

pub fn ch_open(uid: i64, text: &str) -> String {
    format!("🟠 OPEN #{}: {}", uid, text)
}

pub fn ch_wip(who: &str, group: &str, uid: i64) -> String {
    format!(
        "🟢 WIP: {} von [{}] arbeitet jetzt an Ticket #{}.",
        who, group, uid
    )
}

pub fn ch_closed(who: &str, group: &str, uid: i64) -> String {
    format!(
        "✅ CLOSED: {} von [{}] hat Ticket #{} geschlossen.",
        who, group, uid
    )
}

pub fn ch_moved(uid: i64, group: &str) -> String {
    format!("🟠 MOVED #{} to be handled by {}", uid, group)
}

pub fn ch_register(who: &str, group: &str) -> String {
    format!("🔵 {} registered as member of group {}.", who, group)
}

pub fn ch_unregister(who: &str, group: &str) -> String {
    format!("🔵 {} unregistered from group {}.", who, group)
}

pub fn ch_message(sender: &str, recipient: &str, message: &str) -> String {
    format!("🟣 Nachricht von {} an {}: {}", sender, recipient, message)
}

pub fn ch_bot_started(host: &str) -> String {
    format!("🔘 Started from {}", host)
}

// --- Bug / feature reports ---------------------------------------------

pub const BUG_USAGE: &str = "Benutzung: /bug <message>";
pub const BUG_FORWARDED: &str = "Fehlerbericht an Entwickler weitergeleitet.";
pub const FEATURE_USAGE: &str = "Benutzung: /feature <message>";
pub const FEATURE_FORWARDED: &str = "Feature Request an Entwickler weitergeleitet.";

pub fn dev_bug(who: &str, message: &str) -> String {
    format!("⚪️ Bug report von {}: {}", who, message)
}

pub fn dev_feature(who: &str, message: &str) -> String {
    format!("⚪️ feature request von {}: {}", who, message)
}

// --- Unknown -----------------------------------------------------------

pub const UNKNOWN_COMMAND: &str =
    "Kommando nicht erkannt oder im falschen Zusammenhang.\n\n\
     Sende /help um eine Übersicht zu allen verfügbaren Kommandos zu bekommen.";

// --- Engelsystem shift digest ------------------------------------------

pub fn digest_next_shift(time: &str, location: &str) -> String {
    format!("🧑‍🔧 Schicht beginnt um {} an {}:", time, location)
}

pub const DIGEST_NO_ENTRIES: &str = "  (keine Helfer eingetragen)";

pub const ENGELSYSTEM_NOT_CONFIGURED: &str =
    "Deine Gruppe hat keine Schichten im Engelsystem oder der Standort ist nicht korrekt konfiguriert.";
pub const ENGELSYSTEM_LOOKUP_FAILED: &str =
    "Engelsystem-Abfrage fehlgeschlagen. Bitte später erneut versuchen.";
pub const ENGELSYSTEM_NO_SHIFTS: &str =
    "Keine aktuellen oder bevorstehenden Schichten am Standort.";
