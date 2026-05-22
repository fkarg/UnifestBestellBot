//! Channel / dev / group-fanout helpers. They emit [`Action`]s onto
//! the outbox rather than calling teloxide directly, so they're equally
//! exercised by unit tests and the production adapter.

use super::Outbox;
use crate::repo;
use sqlx::SqlitePool;

pub fn channel(outbox: &mut Outbox, text: impl Into<String>) {
    outbox.channel(text);
}

pub fn dev(outbox: &mut Outbox, text: impl Into<String>) {
    outbox.dev(text);
}

/// Fan-out to every member of `group_name`, with the
/// peer-activity / broadcast distinction Python uses:
///
/// - `exclude_chat_id = Some(actor)` ⇒ this is a *peer activity*
///   notification (one of the user's colleagues just did something).
///   The actor is skipped, and members with an active `/quiet` mute
///   are skipped.
/// - `exclude_chat_id = None` ⇒ this is a *broadcast* (an actionable
///   ticket update). Mutes do NOT apply.
pub async fn group_msg(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    group_name: &str,
    text: &str,
    exclude_chat_id: Option<i64>,
) -> anyhow::Result<()> {
    let peer_mode = exclude_chat_id.is_some();
    let members = repo::group_members(pool, group_name, peer_mode).await?;
    for chat_id in members {
        if Some(chat_id) == exclude_chat_id {
            continue;
        }
        outbox.dm(chat_id, text);
    }
    Ok(())
}
