//! Bot handlers. Structured so the per-command logic is **pure** —
//! given (pool, config, user, args, state) it returns a list of
//! [`Action`]s describing what the bot should do (reply, edit message,
//! send a DM, post to the channel, ...). A thin teloxide adapter then
//! executes the actions against a real `Bot`. Behavioural tests can
//! drive the logic functions directly and assert on the action list +
//! DB state.

pub mod adapter;
pub mod admin;
pub mod digest;
pub mod keyboards;
pub mod notify;
pub mod orga;
pub mod register;
pub mod request;
pub mod unknown;

use serde::{Deserialize, Serialize};

/// Inputs that handler logic needs about the calling user — enough to
/// stand in for a teloxide `User` without depending on its types.
#[derive(Debug, Clone)]
pub struct Caller {
    pub chat_id: i64,
    pub username: Option<String>,
    pub first_name: Option<String>,
    pub last_name: Option<String>,
}

impl Caller {
    pub fn anonymous(chat_id: i64) -> Self {
        Self {
            chat_id,
            username: None,
            first_name: None,
            last_name: None,
        }
    }

    /// "Alice Müller <@alice>" — same shape as Python's `who()`.
    pub fn display(&self) -> String {
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
}

/// Reply-keyboard or inline-keyboard variants the adapter knows how to
/// render. Behavioural tests inspect this enum directly.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum Keyboard {
    /// Default reply keyboard for whatever role the user has now.
    /// `is_orga` / `registered` are computed by the logic from the
    /// caller's registration; the adapter just renders.
    AutoSelect { registered: bool, is_orga: bool },
    /// Force a specific reply keyboard.
    Reply(Vec<Vec<String>>),
    /// `ReplyKeyboardRemove`.
    Remove,
    /// Inline keyboard with (label, callback_data) per row.
    Inline(Vec<(String, String)>),
    /// No reply_markup at all.
    None,
}

impl Keyboard {
    pub fn initial() -> Self {
        Self::AutoSelect {
            registered: false,
            is_orga: false,
        }
    }
}

/// Concrete side-effects a handler may emit. The adapter executes them
/// in order; tests inspect them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    /// Reply to the message that triggered the handler.
    Reply {
        text: String,
        keyboard: Keyboard,
    },
    /// Direct message to a specific chat.
    Dm {
        chat_id: i64,
        text: String,
        keyboard: Keyboard,
    },
    /// Post to the updates channel.
    Channel(String),
    /// DM the developer chat.
    Dev(String),
    /// Edit the message a callback was attached to (e.g. picker
    /// selection feedback).
    EditMessage(String),
    /// Answer a callback query — optional toast text, optional alert.
    AnswerCallback {
        text: Option<String>,
        alert: bool,
    },
}

/// Convenience container that lets handlers say `outbox.reply(...)`
/// instead of pushing actions by hand.
#[derive(Debug, Default, Clone)]
pub struct Outbox {
    pub actions: Vec<Action>,
}

impl Outbox {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn reply(&mut self, text: impl Into<String>, keyboard: Keyboard) {
        self.actions.push(Action::Reply {
            text: text.into(),
            keyboard,
        });
    }

    pub fn dm(&mut self, chat_id: i64, text: impl Into<String>) {
        self.actions.push(Action::Dm {
            chat_id,
            text: text.into(),
            keyboard: Keyboard::None,
        });
    }

    pub fn channel(&mut self, text: impl Into<String>) {
        self.actions.push(Action::Channel(text.into()));
    }

    pub fn dev(&mut self, text: impl Into<String>) {
        self.actions.push(Action::Dev(text.into()));
    }

    pub fn edit(&mut self, text: impl Into<String>) {
        self.actions.push(Action::EditMessage(text.into()));
    }

    pub fn answer(&mut self, text: Option<String>, alert: bool) {
        self.actions.push(Action::AnswerCallback { text, alert });
    }

    /// Find all `Reply` action texts — convenience for tests.
    pub fn reply_texts(&self) -> Vec<&str> {
        self.actions
            .iter()
            .filter_map(|a| match a {
                Action::Reply { text, .. } => Some(text.as_str()),
                _ => None,
            })
            .collect()
    }

    /// Find all `Dm` actions — convenience for tests.
    pub fn dms(&self) -> Vec<(&i64, &str)> {
        self.actions
            .iter()
            .filter_map(|a| match a {
                Action::Dm { chat_id, text, .. } => Some((chat_id, text.as_str())),
                _ => None,
            })
            .collect()
    }

    pub fn channel_msgs(&self) -> Vec<&str> {
        self.actions
            .iter()
            .filter_map(|a| match a {
                Action::Channel(t) => Some(t.as_str()),
                _ => None,
            })
            .collect()
    }
}
