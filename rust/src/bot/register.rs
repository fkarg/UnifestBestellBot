//! /start, /help, /register, /unregister, /status, /quiet, /loud.
//!
//! Every handler is a pure-ish async function: it takes the pool and
//! config, mutates an [`Outbox`], and returns. No teloxide types leak
//! in. Behavioural tests inspect the outbox + the DB.

use chrono::Duration;
use sqlx::SqlitePool;

use super::{keyboards, notify, Caller, Keyboard, Outbox};
use crate::config::AppConfig;
use crate::i18n;
use crate::models::{now_utc, Registration};
use crate::repo;

pub const DEFAULT_QUIET_MINUTES: i64 = 30;
pub const MAX_QUIET_MINUTES: i64 = 24 * 60;

// --- /start --------------------------------------------------------------

pub async fn cmd_start(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let reg = repo::registration_for(pool, caller.chat_id).await?;
    outbox.reply(i18n::START, keyboards::for_user(reg.as_ref(), config));
    Ok(())
}

// --- /help ---------------------------------------------------------------

pub async fn cmd_help(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let reg = repo::registration_for(pool, caller.chat_id).await?;
    let text = match &reg {
        Some(r) if config.is_orga(&r.group_name) => i18n::HELP_ORGA,
        _ => i18n::HELP,
    };
    outbox.reply(text, keyboards::for_user(reg.as_ref(), config));
    Ok(())
}

// --- /register -----------------------------------------------------------

/// `/register` with no args opens the inline picker of *visible* stalls.
/// `/register <name>` registers directly, supporting orga and hidden
/// groups too (case-insensitive match against the union of known names).
pub async fn cmd_register(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    arg: Option<&str>,
) -> anyhow::Result<()> {
    if let Some(query) = arg.map(str::trim).filter(|s| !s.is_empty()) {
        register_textual(outbox, pool, config, caller, query).await?;
        return Ok(());
    }

    let mut buttons: Vec<(String, String)> = config
        .visible_stall_names()
        .into_iter()
        .map(|name| (name.to_string(), format!("reg:{}", name)))
        .collect();
    buttons.push((i18n::PICKER_CANCEL.to_string(), "reg:_cancel".to_string()));
    outbox.reply(i18n::REGISTER_PROMPT, Keyboard::Inline(buttons));
    Ok(())
}

async fn register_textual(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    query: &str,
) -> anyhow::Result<()> {
    let mut candidates = config.all_stall_names();
    candidates.extend(config.orga_names());
    let matched = candidates
        .into_iter()
        .find(|g| g.eq_ignore_ascii_case(query))
        .map(|s| s.to_string());

    let Some(group) = matched else {
        outbox.reply(i18n::UNKNOWN_GROUP, keyboards::for_user(None, config));
        return Ok(());
    };

    let reg = Registration {
        chat_id: caller.chat_id,
        group_name: group.clone(),
        username: caller.username.clone(),
        first_name: caller.first_name.clone(),
        last_name: caller.last_name.clone(),
        registered_at: now_utc(),
        mute_peer_until: None,
    };
    let saved = repo::upsert_registration(pool, &reg).await?;
    outbox.reply(
        i18n::register_success(&group),
        keyboards::for_user(Some(&saved), config),
    );
    notify::channel(outbox, i18n::ch_register(&caller.display(), &group));
    Ok(())
}

/// Inline-keyboard callback path. Defence-in-depth: only visible stalls
/// can be selected here — orga and hidden groups need the textual arg.
pub async fn on_register_choice(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    choice: &str,
) -> anyhow::Result<()> {
    if choice == "_cancel" {
        outbox.edit(i18n::REGISTER_CANCELLED);
        outbox.answer(None, false);
        return Ok(());
    }
    if !config.visible_stall_names().contains(&choice) {
        outbox.answer(Some(i18n::UNKNOWN_GROUP.into()), true);
        return Ok(());
    }

    let reg = Registration {
        chat_id: caller.chat_id,
        group_name: choice.to_string(),
        username: caller.username.clone(),
        first_name: caller.first_name.clone(),
        last_name: caller.last_name.clone(),
        registered_at: now_utc(),
        mute_peer_until: None,
    };
    let saved = repo::upsert_registration(pool, &reg).await?;
    outbox.edit(i18n::register_success(choice));
    outbox.actions.push(super::Action::Dm {
        chat_id: caller.chat_id,
        text: i18n::REGISTER_KEYBOARD_UPDATE.into(),
        keyboard: keyboards::for_user(Some(&saved), config),
    });
    notify::channel(outbox, i18n::ch_register(&caller.display(), choice));
    outbox.answer(None, false);
    Ok(())
}

// --- /unregister ---------------------------------------------------------

pub async fn cmd_unregister(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    match repo::unregister(pool, caller.chat_id).await? {
        Some(prev) => {
            outbox.reply(
                i18n::unregister_success(&prev),
                keyboards::for_user(None, config),
            );
            notify::channel(outbox, i18n::ch_unregister(&caller.display(), &prev));
        }
        None => {
            outbox.reply(i18n::UNREGISTER_NONE, keyboards::for_user(None, config));
        }
    }
    Ok(())
}

// --- /status -------------------------------------------------------------

pub async fn cmd_status(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let Some(reg) = repo::registration_for(pool, caller.chat_id).await? else {
        outbox.reply(
            i18n::STATUS_NO_REGISTRATION,
            keyboards::for_user(None, config),
        );
        return Ok(());
    };
    let open = repo::tickets_requested_by(pool, &reg.group_name).await?;
    let kb = keyboards::for_user(Some(&reg), config);
    if open.is_empty() {
        outbox.reply(i18n::status_no_tickets(&reg.group_name), kb);
    } else {
        let body = open
            .iter()
            .map(|t| t.display())
            .collect::<Vec<_>>()
            .join("\n\n---\n");
        outbox.reply(
            i18n::status_with_tickets(&reg.group_name, open.len(), &body),
            kb,
        );
    }
    Ok(())
}

// --- /quiet / /loud ------------------------------------------------------

pub async fn cmd_quiet(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
    arg: Option<&str>,
) -> anyhow::Result<()> {
    let Some(reg) = repo::registration_for(pool, caller.chat_id).await? else {
        outbox.reply(i18n::NOT_REGISTERED, keyboards::for_user(None, config));
        return Ok(());
    };

    let kb = keyboards::for_user(Some(&reg), config);
    let minutes = match arg.map(str::trim).filter(|s| !s.is_empty()) {
        None => DEFAULT_QUIET_MINUTES,
        Some(s) => match s.parse::<i64>() {
            Ok(n) if (1..=MAX_QUIET_MINUTES).contains(&n) => n,
            _ => {
                outbox.reply(i18n::QUIET_USAGE, kb);
                return Ok(());
            }
        },
    };

    let until = now_utc() + Duration::minutes(minutes);
    repo::set_mute(pool, caller.chat_id, Some(until)).await?;
    outbox.reply(i18n::quiet_set(minutes as u32), kb);
    Ok(())
}

pub async fn cmd_loud(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    caller: &Caller,
) -> anyhow::Result<()> {
    let Some(reg) = repo::registration_for(pool, caller.chat_id).await? else {
        outbox.reply(i18n::NOT_REGISTERED, keyboards::for_user(None, config));
        return Ok(());
    };

    let was_muted = reg.mute_peer_until.is_some();
    repo::set_mute(pool, caller.chat_id, None).await?;
    let kb = keyboards::for_user(Some(&reg), config);
    outbox.reply(
        if was_muted {
            i18n::LOUD_SET
        } else {
            i18n::LOUD_ALREADY
        },
        kb,
    );
    Ok(())
}
