//! Persisted data model. Shapes match the Python `models.py` so the
//! same `bot.db` can be opened by either implementation.
//!
//! Datetimes are **naive UTC** (`NaiveDateTime`) — SQLite drops timezone
//! info on round-trip, and the Python side standardised on naive UTC to
//! avoid the silent tz-mixing bug. We do the same here so the two
//! implementations stay binary-compatible at the storage layer.

use chrono::NaiveDateTime;
use serde::{Deserialize, Serialize};
use std::fmt;

/// Lifecycle status of a ticket. The string values are the on-wire and
/// on-disk encoding — matching the Python `TicketStatus(StrEnum)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TicketStatus {
    Open,
    Wip,
    Closed,
}

impl TicketStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            TicketStatus::Open => "open",
            TicketStatus::Wip => "wip",
            TicketStatus::Closed => "closed",
        }
    }

    pub fn display(self) -> &'static str {
        match self {
            TicketStatus::Open => "🟠 OPEN",
            TicketStatus::Wip => "🟢 WIP",
            TicketStatus::Closed => "✅ CLOSED",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "open" => Some(Self::Open),
            "wip" => Some(Self::Wip),
            "closed" => Some(Self::Closed),
            _ => None,
        }
    }
}

impl fmt::Display for TicketStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Returns naive UTC for stored datetimes.
pub fn now_utc() -> NaiveDateTime {
    chrono::Utc::now().naive_utc()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Registration {
    pub chat_id: i64,
    pub group_name: String,
    pub username: Option<String>,
    pub first_name: Option<String>,
    pub last_name: Option<String>,
    pub registered_at: NaiveDateTime,
    pub mute_peer_until: Option<NaiveDateTime>,
}

impl Registration {
    pub fn new(chat_id: i64, group_name: impl Into<String>) -> Self {
        Self {
            chat_id,
            group_name: group_name.into(),
            username: None,
            first_name: None,
            last_name: None,
            registered_at: now_utc(),
            mute_peer_until: None,
        }
    }

    pub fn display_name(&self) -> String {
        let parts: Vec<&str> = [self.first_name.as_deref(), self.last_name.as_deref()]
            .into_iter()
            .flatten()
            .collect();
        let name = if parts.is_empty() {
            "Unbekannt".to_string()
        } else {
            parts.join(" ")
        };
        match &self.username {
            Some(u) => format!("{} <@{}>", name, u),
            None => name,
        }
    }

    pub fn is_currently_muted(&self, now: NaiveDateTime) -> bool {
        match self.mute_peer_until {
            Some(t) => t > now,
            None => false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Ticket {
    pub id: i64,
    pub status: TicketStatus,
    pub category: String,
    pub text: String,
    pub group_requesting: String,
    pub group_tasked: String,
    pub who_wip: Option<String>,
    pub created_at: NaiveDateTime,
    pub closed_at: Option<NaiveDateTime>,
}

impl Ticket {
    pub fn display(&self) -> String {
        format!("{} #{}: {}", self.status.display(), self.id, self.text)
    }

    pub fn is_open(&self) -> bool {
        self.status == TicketStatus::Open
    }

    pub fn is_wip(&self) -> bool {
        self.status == TicketStatus::Wip
    }

    pub fn is_closed(&self) -> bool {
        self.status == TicketStatus::Closed
    }
}

/// Append-only audit log. `payload_json` carries kind-specific data
/// (closer name on `close`, from/to on `move`, the message body on
/// `message`, etc.) — kept as opaque JSON so the schema doesn't change
/// when new kinds are introduced.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AuditEvent {
    pub id: i64,
    pub ts: NaiveDateTime,
    pub kind: String,
    pub ticket_id: Option<i64>,
    pub actor_chat_id: Option<i64>,
    pub payload_json: Option<String>,
}
