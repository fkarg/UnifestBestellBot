//! Developer-only commands. /closeall is the only one currently in
//! the contract — it fans out per-ticket CLOSED notifications the
//! same way /close does, attributing the closer to a virtual
//! "Entwickler" group in the channel log.

use sqlx::SqlitePool;

use super::{Caller, Outbox};
use crate::config::AppConfig;
use crate::i18n;
use crate::models::TicketStatus;
use crate::repo;

pub const DEVELOPER_ACTOR_GROUP: &str = "Entwickler";

pub async fn cmd_closeall(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    _config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let open = repo::active_tickets(pool, None, None).await?;
    let mut closed = 0;
    for t in open {
        if t.status == TicketStatus::Closed {
            continue;
        }
        // Close + fan-out same as /close, but attribute to "Entwickler".
        let _ = repo::close_ticket(pool, t.id, caller.chat_id).await?;
        outbox.channel(i18n::ch_closed(
            &caller.display(),
            DEVELOPER_ACTOR_GROUP,
            t.id,
        ));
        crate::bot::notify::group_msg(
            outbox,
            pool,
            &t.group_requesting,
            &i18n::group_ticket_closed_owner(t.id),
            None,
        )
        .await?;
        crate::bot::notify::group_msg(
            outbox,
            pool,
            &t.group_tasked,
            &i18n::group_ticket_closed_peer(&caller.display(), t.id),
            None,
        )
        .await?;
        closed += 1;
    }
    outbox.reply(
        format!("☑️ Closed {} ticket(s).", closed),
        super::Keyboard::None,
    );
    outbox.dev(format!("☑️ /closeall closed {} ticket(s).", closed));
    Ok(())
}
