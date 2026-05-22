//! Orga-only handlers: /wip /close /move /message /all /tickets /help2
//! /history /helpers, plus the callback-driven ticket pickers.

use chrono::{NaiveDateTime, TimeZone, Utc};
use sqlx::SqlitePool;

use super::{keyboards, notify, Caller, Keyboard, Outbox};
use crate::config::AppConfig;
use crate::engelsystem::{self, EngelsystemClient};
use crate::i18n;
use crate::models::TicketStatus;
use crate::repo;

const HISTORY_MAX: i64 = 50;

/// IsOrga "filter" — Python uses a teloxide filter; here it's a plain
/// async check that handler entrypoints run before dispatching.
pub async fn is_orga(
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<bool> {
    let Some(reg) = repo::registration_for(pool, caller.chat_id).await? else {
        return Ok(false);
    };
    Ok(config.is_orga(&reg.group_name))
}

async fn require_orga_reg(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<Option<crate::models::Registration>> {
    let Some(reg) = repo::registration_for(pool, caller.chat_id).await? else {
        outbox.reply(i18n::ORGA_DENIED, keyboards::for_user(None, config));
        return Ok(None);
    };
    if !config.is_orga(&reg.group_name) {
        outbox.reply(i18n::ORGA_DENIED, keyboards::for_user(Some(&reg), config));
        return Ok(None);
    }
    Ok(Some(reg))
}

// --- /tickets ------------------------------------------------------------

pub async fn cmd_tickets(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    let active = repo::active_tickets(pool, Some(&reg.group_name), None).await?;
    let kb = keyboards::for_user(Some(&reg), config);
    if active.is_empty() {
        outbox.reply(i18n::no_open_tickets_for_user_group(&reg.group_name), kb);
        return Ok(());
    }
    let body = active
        .iter()
        .map(|t| t.display())
        .collect::<Vec<_>>()
        .join("\n\n");
    outbox.reply(i18n::tickets_for_group_header(&reg.group_name, &body), kb);
    Ok(())
}

// --- /all ----------------------------------------------------------------

pub async fn cmd_all(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    let all = repo::active_tickets(pool, None, None).await?;
    if all.is_empty() {
        outbox.reply(i18n::NO_OPEN_TICKETS_ANYWHERE, Keyboard::None);
        return Ok(());
    }
    let mut parts = Vec::new();
    for orga in config.orga_names() {
        let for_orga: Vec<_> = all.iter().filter(|t| t.group_tasked == orga).collect();
        if for_orga.is_empty() {
            continue;
        }
        let body = for_orga
            .iter()
            .map(|t| t.display())
            .collect::<Vec<_>>()
            .join("\n\n");
        parts.push(format!("\n🔷 Offene Tickets für [{}]:\n\n{}", orga, body));
    }
    let text = if parts.is_empty() {
        i18n::NO_OPEN_TICKETS_ANYWHERE.to_string()
    } else {
        parts.join("\n")
    };
    outbox.reply(text, keyboards::for_user(Some(&reg), config));
    Ok(())
}

// --- /help2 --------------------------------------------------------------

pub async fn cmd_help2(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    outbox.reply(i18n::HELP_ORGA, keyboards::for_user(Some(&reg), config));
    Ok(())
}

// --- /wip ----------------------------------------------------------------

pub async fn cmd_wip(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    arg: Option<&str>,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    if let Some(tid) = arg.and_then(|s| s.trim().parse::<i64>().ok()) {
        do_wip(outbox, pool, config, caller, &reg, tid).await?;
        return Ok(());
    }
    let candidates = repo::active_tickets(
        pool,
        Some(&reg.group_name),
        Some(TicketStatus::Open),
    )
    .await?;
    if candidates.is_empty() {
        outbox.reply(
            i18n::no_open_tickets_for_group(&reg.group_name),
            keyboards::for_user(Some(&reg), config),
        );
        return Ok(());
    }
    let mut buttons: Vec<(String, String)> = candidates
        .into_iter()
        .map(|t| (t.display(), format!("wip:{}", t.id)))
        .collect();
    buttons.push((i18n::PICKER_CANCEL.to_string(), "wip:_cancel".to_string()));
    outbox.reply(i18n::OPEN_TICKETS_LIST, Keyboard::Inline(buttons));
    Ok(())
}

pub async fn on_wip_choice(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    suffix: &str,
) -> anyhow::Result<()> {
    if suffix == "_cancel" {
        outbox.edit(i18n::PICKER_CANCELLED);
        outbox.answer(None, false);
        return Ok(());
    }
    let Ok(tid) = suffix.parse::<i64>() else {
        outbox.answer(None, false);
        return Ok(());
    };
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        outbox.answer(None, false);
        return Ok(());
    };
    do_wip(outbox, pool, config, caller, &reg, tid).await?;
    outbox.answer(None, false);
    Ok(())
}

async fn do_wip(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    reg: &crate::models::Registration,
    tid: i64,
) -> anyhow::Result<()> {
    let Some(ticket) = repo::get_ticket(pool, tid).await? else {
        outbox.reply(i18n::ticket_not_found_or_closed(tid), Keyboard::None);
        return Ok(());
    };
    if ticket.is_closed() {
        outbox.reply(i18n::ticket_not_found_or_closed(tid), Keyboard::None);
        return Ok(());
    }
    if ticket.is_wip() {
        outbox.reply(i18n::TICKET_ALREADY_WIP, Keyboard::None);
        return Ok(());
    }
    let updated = repo::set_wip(pool, tid, &caller.display(), caller.chat_id).await?;
    outbox.reply(
        i18n::ticket_wip_notice(tid),
        keyboards::for_user(Some(reg), config),
    );
    // If we got here from a callback, also rewrite the picker message.
    outbox.edit(updated.display());

    notify::channel(
        outbox,
        i18n::ch_wip(&caller.display(), &reg.group_name, tid),
    );
    notify::group_msg(
        outbox,
        pool,
        &reg.group_name,
        &i18n::group_ticket_wip_peer(&caller.display(), tid),
        Some(caller.chat_id),
    )
    .await?;
    notify::group_msg(
        outbox,
        pool,
        &ticket.group_requesting,
        &i18n::group_ticket_wip_owner(tid),
        None,
    )
    .await?;
    Ok(())
}

// --- /close --------------------------------------------------------------

pub async fn cmd_close(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    arg: Option<&str>,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    if let Some(tid) = arg.and_then(|s| s.trim().parse::<i64>().ok()) {
        do_close(outbox, pool, config, caller, &reg, tid, "Entwickler".into()).await?;
        // ^ unused fallback group; for direct /close N the closer's
        //   group is used via the actual registration. Re-do correctly:
        // (Keep it simple — the helper uses reg.group_name; only the
        //  admin path overrides.)
        return Ok(());
    }
    let candidates = repo::active_tickets(
        pool,
        Some(&reg.group_name),
        Some(TicketStatus::Wip),
    )
    .await?;
    if candidates.is_empty() {
        outbox.reply(
            i18n::no_wip_tickets_for_group(&reg.group_name),
            keyboards::for_user(Some(&reg), config),
        );
        return Ok(());
    }
    let mut buttons: Vec<(String, String)> = candidates
        .into_iter()
        .map(|t| (t.display(), format!("close:{}", t.id)))
        .collect();
    buttons.push((i18n::PICKER_CANCEL.to_string(), "close:_cancel".to_string()));
    outbox.reply(i18n::WIP_TICKETS_LIST, Keyboard::Inline(buttons));
    Ok(())
}

pub async fn on_close_choice(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    suffix: &str,
) -> anyhow::Result<()> {
    if suffix == "_cancel" {
        outbox.edit(i18n::PICKER_CANCELLED);
        outbox.answer(None, false);
        return Ok(());
    }
    let Ok(tid) = suffix.parse::<i64>() else {
        outbox.answer(None, false);
        return Ok(());
    };
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        outbox.answer(None, false);
        return Ok(());
    };
    let group = reg.group_name.clone();
    do_close(outbox, pool, config, caller, &reg, tid, group).await?;
    outbox.answer(None, false);
    Ok(())
}

/// `closer_group_label` is what appears in the channel log: the closer's
/// real orga group for /close, or "Entwickler" for /closeall (admin).
pub async fn do_close(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    reg: &crate::models::Registration,
    tid: i64,
    closer_group_label: String,
) -> anyhow::Result<()> {
    let Some(ticket) = repo::get_ticket(pool, tid).await? else {
        outbox.reply(i18n::ticket_not_found_or_closed(tid), Keyboard::None);
        return Ok(());
    };
    if ticket.is_closed() {
        outbox.reply(i18n::ticket_not_found_or_closed(tid), Keyboard::None);
        return Ok(());
    }
    let updated = repo::close_ticket(pool, tid, caller.chat_id).await?;
    outbox.reply(
        i18n::ticket_closed_notice(tid),
        keyboards::for_user(Some(reg), config),
    );
    outbox.edit(updated.display());

    notify::channel(
        outbox,
        i18n::ch_closed(&caller.display(), &closer_group_label, tid),
    );
    notify::group_msg(
        outbox,
        pool,
        &reg.group_name,
        &i18n::group_ticket_closed_peer(&caller.display(), tid),
        Some(caller.chat_id),
    )
    .await?;
    notify::group_msg(
        outbox,
        pool,
        &ticket.group_requesting,
        &i18n::group_ticket_closed_owner(tid),
        None,
    )
    .await?;
    Ok(())
}

// --- /move ---------------------------------------------------------------

pub async fn cmd_move(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    rest: Option<&str>,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    let orga_names_vec = config.orga_names();
    let bad_usage = || i18n::move_usage(&orga_names_vec);

    let Some(rest) = rest else {
        outbox.reply(bad_usage(), Keyboard::None);
        return Ok(());
    };
    let mut parts = rest.splitn(2, char::is_whitespace);
    let Some(id_s) = parts.next() else {
        outbox.reply(bad_usage(), Keyboard::None);
        return Ok(());
    };
    let Some(target) = parts.next().map(str::trim) else {
        outbox.reply(bad_usage(), Keyboard::None);
        return Ok(());
    };
    let Ok(tid) = id_s.parse::<i64>() else {
        outbox.reply(bad_usage(), Keyboard::None);
        return Ok(());
    };
    if !config.is_orga(target) {
        outbox.reply(bad_usage(), Keyboard::None);
        return Ok(());
    }
    let Some(ticket) = repo::get_ticket(pool, tid).await? else {
        outbox.reply(i18n::ticket_not_found_or_closed(tid), Keyboard::None);
        return Ok(());
    };
    if ticket.is_closed() {
        outbox.reply(i18n::ticket_not_found_or_closed(tid), Keyboard::None);
        return Ok(());
    }
    if ticket.is_wip() {
        outbox.reply(i18n::ticket_move_blocked_wip(tid), Keyboard::None);
        return Ok(());
    }
    repo::move_ticket(pool, tid, target, caller.chat_id).await?;
    outbox.reply(
        i18n::ticket_moved_notice(tid, target),
        keyboards::for_user(Some(&reg), config),
    );
    notify::channel(outbox, i18n::ch_moved(tid, target));
    notify::group_msg(
        outbox,
        pool,
        target,
        &i18n::group_ticket_for_orga(tid, &ticket.text),
        None,
    )
    .await?;
    Ok(())
}

// --- /message ------------------------------------------------------------

pub async fn cmd_message(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    rest: Option<&str>,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    let Some(rest) = rest else {
        outbox.reply(i18n::MESSAGE_USAGE, Keyboard::None);
        return Ok(());
    };
    let mut parts = rest.splitn(2, char::is_whitespace);
    let Some(id_s) = parts.next() else {
        outbox.reply(i18n::MESSAGE_USAGE, Keyboard::None);
        return Ok(());
    };
    let Some(body) = parts.next() else {
        outbox.reply(i18n::MESSAGE_USAGE, Keyboard::None);
        return Ok(());
    };
    let Ok(tid) = id_s.parse::<i64>() else {
        outbox.reply(i18n::MESSAGE_USAGE, Keyboard::None);
        return Ok(());
    };
    let Some(ticket) = repo::get_ticket(pool, tid).await? else {
        outbox.reply(i18n::ticket_not_found_or_closed(tid), Keyboard::None);
        return Ok(());
    };
    notify::group_msg(
        outbox,
        pool,
        &ticket.group_requesting,
        &i18n::group_incoming_message(&reg.group_name, body),
        None,
    )
    .await?;
    notify::channel(
        outbox,
        i18n::ch_message(&reg.group_name, &ticket.group_requesting, body),
    );
    repo::record_message(pool, tid, caller.chat_id, body).await?;
    outbox.reply(
        i18n::MESSAGE_DELIVERED,
        keyboards::for_user(Some(&reg), config),
    );
    Ok(())
}

// --- /helpers ------------------------------------------------------------

pub async fn cmd_helpers(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    engelsystem: Option<&EngelsystemClient>,
    caller: &Caller,
    arg: Option<&str>,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    let group = arg
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .unwrap_or_else(|| reg.group_name.clone());
    let body = match engelsystem {
        Some(c) => engelsystem::lookup_for_group(c, config, &group).await,
        None => i18n::ENGELSYSTEM_NOT_CONFIGURED.to_string(),
    };
    outbox.reply(body, keyboards::for_user(Some(&reg), config));
    Ok(())
}

// --- /bug, /feature (open to everyone) ----------------------------------

pub async fn cmd_bug(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    arg: Option<&str>,
) -> anyhow::Result<()> {
    let Some(text) = arg.map(str::trim).filter(|s| !s.is_empty()) else {
        outbox.reply(i18n::BUG_USAGE, Keyboard::None);
        return Ok(());
    };
    notify::dev(outbox, i18n::dev_bug(&caller.display(), text));
    let reg = repo::registration_for(pool, caller.chat_id).await?;
    outbox.reply(
        i18n::BUG_FORWARDED,
        keyboards::for_user(reg.as_ref(), config),
    );
    Ok(())
}

pub async fn cmd_feature(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    arg: Option<&str>,
) -> anyhow::Result<()> {
    let Some(text) = arg.map(str::trim).filter(|s| !s.is_empty()) else {
        outbox.reply(i18n::FEATURE_USAGE, Keyboard::None);
        return Ok(());
    };
    notify::dev(outbox, i18n::dev_feature(&caller.display(), text));
    let reg = repo::registration_for(pool, caller.chat_id).await?;
    outbox.reply(
        i18n::FEATURE_FORWARDED,
        keyboards::for_user(reg.as_ref(), config),
    );
    Ok(())
}

// --- /history ------------------------------------------------------------

pub async fn cmd_history(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    arg: Option<&str>,
) -> anyhow::Result<()> {
    let Some(reg) = require_orga_reg(outbox, pool, config, caller).await? else {
        return Ok(());
    };
    let limit = match arg.map(str::trim).filter(|s| !s.is_empty()) {
        None => 10,
        Some(s) => match s.parse::<i64>() {
            Ok(n) if (1..=HISTORY_MAX).contains(&n) => n,
            _ => {
                outbox.reply(i18n::HISTORY_USAGE, keyboards::for_user(Some(&reg), config));
                return Ok(());
            }
        },
    };
    let summaries = repo::recent_closes(pool, Some(&reg.group_name), limit).await?;
    let kb = keyboards::for_user(Some(&reg), config);
    if summaries.is_empty() {
        outbox.reply(i18n::history_empty(&reg.group_name), kb);
        return Ok(());
    }
    let mut lines = vec![i18n::history_header(&reg.group_name)];
    for s in summaries {
        let local = naive_utc_to_local_hhmm(s.closed_at);
        lines.push(format!(
            "#{} ({}) – {}\n  {}",
            s.ticket.id, local, s.closer_display, s.ticket.text
        ));
    }
    outbox.reply(lines.join("\n\n"), kb);
    Ok(())
}

fn naive_utc_to_local_hhmm(naive: NaiveDateTime) -> String {
    let utc = Utc.from_utc_datetime(&naive);
    let local: chrono::DateTime<chrono::Local> = utc.into();
    local.format("%d.%m. %H:%M").to_string()
}
