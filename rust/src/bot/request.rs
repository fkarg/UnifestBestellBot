//! /request conversation. Pure state machine — every step takes the
//! current [`RequestState`] and the user's input, returns the new state
//! and emits actions onto an [`Outbox`].

use sqlx::SqlitePool;

use super::{keyboards, notify, Caller, Keyboard, Outbox};
use crate::config::AppConfig;
use crate::engelsystem::{self, EngelsystemClient};
use crate::events::EventBus;
use crate::i18n;
use crate::models::Ticket;
use crate::repo;

/// Conversation state. Equivalent to the Python `RequestFSM` plus the
/// `data` dict on `FSMContext`. Idle = no conversation in flight.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub enum RequestState {
    #[default]
    Idle,
    Category {
        group: String,
    },
    Money {
        group: String,
        category: String,
    },
    MoneyChange {
        group: String,
        category: String,
    },
    Cups {
        group: String,
        category: String,
    },
    Amount {
        group: String,
        category: String,
        detail: String,
    },
    Free {
        group: String,
        category: String,
    },
    Helper {
        group: String,
        category: String,
    },
}

const CATEGORIES: &[&str] = &["Becher", "Geld", "Bier", "Cocktail", "Sonstiges", "Helfer"];

// --- /cancel / /request entry -------------------------------------------

pub async fn cmd_cancel(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    state: RequestState,
) -> anyhow::Result<RequestState> {
    let reg = repo::registration_for(pool, caller.chat_id).await?;
    outbox.reply(i18n::REQUEST_CANCELLED, keyboards::for_user(reg.as_ref(), config));
    let _ = state; // explicitly discard prior state
    Ok(RequestState::Idle)
}

pub async fn cmd_request(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    state: RequestState,
) -> anyhow::Result<RequestState> {
    if state != RequestState::Idle {
        outbox.reply(i18n::REQUEST_IN_PROGRESS, Keyboard::None);
        return Ok(state);
    }
    let Some(reg) = repo::registration_for(pool, caller.chat_id).await? else {
        outbox.reply(i18n::NOT_REGISTERED, keyboards::for_user(None, config));
        return Ok(RequestState::Idle);
    };
    outbox.reply(i18n::REQUEST_INTRO, keyboards::categories());
    Ok(RequestState::Category {
        group: reg.group_name,
    })
}

// --- Category step -------------------------------------------------------

pub async fn on_text(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    events: &EventBus,
    engelsystem: Option<&EngelsystemClient>,
    caller: &Caller,
    state: RequestState,
    text: &str,
) -> anyhow::Result<RequestState> {
    match state {
        RequestState::Idle => Ok(RequestState::Idle),
        RequestState::Category { group } => category_step(outbox, group, text).await,
        RequestState::Money { group, category } => {
            money_step(outbox, pool, config, events, caller, group, category, text).await
        }
        RequestState::MoneyChange { group, category } => {
            money_change_step(outbox, pool, config, events, caller, group, category, text).await
        }
        RequestState::Cups { group, category } => {
            cups_step(outbox, pool, config, events, caller, group, category, text).await
        }
        RequestState::Amount {
            group,
            category,
            detail,
        } => {
            amount_step(
                outbox, pool, config, events, caller, group, category, detail, text,
            )
            .await
        }
        RequestState::Free { group, category } => {
            free_step(outbox, pool, config, events, caller, group, category, text).await
        }
        RequestState::Helper { group, category } => {
            helper_step(
                outbox,
                pool,
                config,
                engelsystem,
                caller,
                group,
                category,
                text,
            )
            .await
        }
    }
}

async fn category_step(
    outbox: &mut Outbox,
    group: String,
    text: &str,
) -> anyhow::Result<RequestState> {
    if !CATEGORIES.contains(&text) {
        outbox.reply(i18n::REQUEST_CATEGORY_UNKNOWN, keyboards::categories());
        return Ok(RequestState::Category { group });
    }
    let cat = text.to_string();
    let (next, kb, prompt) = match text {
        "Geld" => (
            RequestState::Money {
                group: group.clone(),
                category: cat.clone(),
            },
            keyboards::money(),
            i18n::ASK_MONEY,
        ),
        "Becher" => (
            RequestState::Cups {
                group: group.clone(),
                category: cat.clone(),
            },
            keyboards::cups(),
            i18n::ASK_CUPS,
        ),
        "Bier" | "Cocktail" | "Sonstiges" => (
            RequestState::Free {
                group: group.clone(),
                category: cat.clone(),
            },
            Keyboard::Remove,
            i18n::ASK_FREE,
        ),
        "Helfer" => (
            RequestState::Helper {
                group: group.clone(),
                category: cat.clone(),
            },
            keyboards::helper(),
            i18n::ASK_HELPER,
        ),
        _ => unreachable!("filtered above"),
    };
    outbox.reply(prompt, kb);
    Ok(next)
}

// --- Money branches ------------------------------------------------------

#[allow(clippy::too_many_arguments)]
async fn money_step(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    events: &EventBus,
    caller: &Caller,
    group: String,
    category: String,
    text: &str,
) -> anyhow::Result<RequestState> {
    match text {
        "Geld Abholen" => {
            let stand = config.display_for(&group);
            let body = format!("{} abholen an {}", category, stand);
            finalize(outbox, pool, config, events, caller, &group, &category, &body).await?;
            Ok(RequestState::Idle)
        }
        "Wechselgeld" => {
            outbox.reply(i18n::ASK_MONEY_CHANGE, keyboards::money_change());
            Ok(RequestState::MoneyChange { group, category })
        }
        "Freitext" => {
            outbox.reply(i18n::ASK_FREE, Keyboard::Remove);
            Ok(RequestState::Free { group, category })
        }
        _ => {
            outbox.reply(i18n::REQUEST_CATEGORY_UNKNOWN, keyboards::money());
            Ok(RequestState::Money { group, category })
        }
    }
}

#[allow(clippy::too_many_arguments)]
async fn money_change_step(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    events: &EventBus,
    caller: &Caller,
    group: String,
    category: String,
    text: &str,
) -> anyhow::Result<RequestState> {
    match text {
        "Scheine" | "Münzen" => {
            let stand = config.display_for(&group);
            let body = format!("{} braucht {}", stand, text);
            finalize(outbox, pool, config, events, caller, &group, &category, &body).await?;
            Ok(RequestState::Idle)
        }
        _ => {
            outbox.reply(i18n::REQUEST_CATEGORY_UNKNOWN, keyboards::money_change());
            Ok(RequestState::MoneyChange { group, category })
        }
    }
}

// --- Cups branches -------------------------------------------------------

#[allow(clippy::too_many_arguments)]
async fn cups_step(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    events: &EventBus,
    caller: &Caller,
    group: String,
    category: String,
    text: &str,
) -> anyhow::Result<RequestState> {
    match text {
        "Dreckige Abholen" => {
            let stand = config.display_for(&group);
            let body = format!("{} abholen an {}", category, stand);
            finalize(outbox, pool, config, events, caller, &group, &category, &body).await?;
            Ok(RequestState::Idle)
        }
        "Shotbecher" | "Normale Becher" => {
            outbox.reply(i18n::ASK_AMOUNT, keyboards::amount());
            Ok(RequestState::Amount {
                group,
                category,
                detail: text.to_string(),
            })
        }
        _ => {
            outbox.reply(i18n::REQUEST_CATEGORY_UNKNOWN, keyboards::cups());
            Ok(RequestState::Cups { group, category })
        }
    }
}

// --- Amount --------------------------------------------------------------

#[allow(clippy::too_many_arguments)]
async fn amount_step(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    events: &EventBus,
    caller: &Caller,
    group: String,
    category: String,
    detail: String,
    text: &str,
) -> anyhow::Result<RequestState> {
    if text == "Freitext" {
        outbox.reply(i18n::ASK_FREE, Keyboard::Remove);
        return Ok(RequestState::Free { group, category });
    }
    let stand = config.display_for(&group);
    let body = format!("{} hat noch {} {}", stand, text, detail);
    finalize(outbox, pool, config, events, caller, &group, &category, &body).await?;
    Ok(RequestState::Idle)
}

// --- Free text -----------------------------------------------------------

#[allow(clippy::too_many_arguments)]
async fn free_step(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    events: &EventBus,
    caller: &Caller,
    group: String,
    category: String,
    text: &str,
) -> anyhow::Result<RequestState> {
    let stand = config.display_for(&group);
    let body = format!("{} braucht {}: '{}'", stand, category, text);
    finalize(outbox, pool, config, events, caller, &group, &category, &body).await?;
    Ok(RequestState::Idle)
}

// --- Helper --------------------------------------------------------------

#[allow(clippy::too_many_arguments)]
async fn helper_step(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    engelsystem: Option<&EngelsystemClient>,
    caller: &Caller,
    group: String,
    category: String,
    text: &str,
) -> anyhow::Result<RequestState> {
    match text {
        "Liste Schichten" => {
            let body = match engelsystem {
                Some(c) => engelsystem::lookup_for_group(c, config, &group).await,
                None => i18n::ENGELSYSTEM_NOT_CONFIGURED.to_string(),
            };
            let reg = repo::registration_for(pool, caller.chat_id).await?;
            outbox.reply(body, keyboards::for_user(reg.as_ref(), config));
            Ok(RequestState::Idle)
        }
        "Helfer nicht da" => {
            outbox.reply(i18n::ASK_HELPER_FREE, Keyboard::Remove);
            Ok(RequestState::Free { group, category })
        }
        // Anything else (zu viele / zu wenige / free text) falls through
        // to the amount question.
        _ => {
            outbox.reply(i18n::ASK_AMOUNT, keyboards::amount());
            Ok(RequestState::Amount {
                group,
                category,
                detail: text.to_string(),
            })
        }
    }
}

// --- Finalize ------------------------------------------------------------

#[allow(clippy::too_many_arguments)]
async fn finalize(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    events: &EventBus,
    caller: &Caller,
    group: &str,
    category: &str,
    text: &str,
) -> anyhow::Result<Ticket> {
    let orga = config.route_category(category).to_string();
    let ticket = repo::create_ticket(pool, category, text, group, &orga, caller.chat_id).await?;

    let reg = repo::registration_for(pool, caller.chat_id).await?;
    outbox.reply(
        i18n::request_ticket_created(ticket.id, &orga),
        keyboards::for_user(reg.as_ref(), config),
    );

    events.publish_ticket(&ticket);
    notify::channel(outbox, i18n::ch_open(ticket.id, text));
    notify::group_msg(
        outbox,
        pool,
        group,
        &i18n::group_ticket_opened(&caller.display(), text),
        Some(caller.chat_id),
    )
    .await?;
    notify::group_msg(
        outbox,
        pool,
        &orga,
        &i18n::group_ticket_for_orga(ticket.id, text),
        None,
    )
    .await?;
    Ok(ticket)
}
