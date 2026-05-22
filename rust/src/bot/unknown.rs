//! Fallback for messages that no other handler claims. Mirrors the
//! Python `bot/unknown.py`.

use sqlx::SqlitePool;

use super::{keyboards, Caller, Outbox};
use crate::config::AppConfig;
use crate::i18n;
use crate::repo;

pub async fn cmd_unknown(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let reg = repo::registration_for(pool, caller.chat_id).await?;
    outbox.reply(
        i18n::UNKNOWN_COMMAND,
        keyboards::for_user(reg.as_ref(), config),
    );
    Ok(())
}
