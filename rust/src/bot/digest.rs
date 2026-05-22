//! Engelsystem shift-start digest. Pure stepper + a looping driver.

use chrono::{DateTime, Duration, FixedOffset, Local, NaiveDateTime, NaiveTime, TimeZone, Utc};
use sqlx::SqlitePool;
use std::collections::HashSet;

use super::{notify, Outbox};
use crate::config::AppConfig;
use crate::engelsystem::EngelsystemClient;
use crate::i18n;
use crate::models::now_utc;

pub fn is_within_window(now_local: NaiveTime, start: NaiveTime, end: NaiveTime) -> bool {
    if start == end {
        return true; // always-on
    }
    if start < end {
        return start <= now_local && now_local < end;
    }
    now_local >= start || now_local < end
}

fn parse_iso(s: &str) -> Option<DateTime<FixedOffset>> {
    DateTime::parse_from_rfc3339(s).ok()
}

fn format_shift_announcement(shift: &serde_json::Value, location_name: &str) -> String {
    let local = shift
        .get("starts_at")
        .and_then(|v| v.as_str())
        .and_then(parse_iso)
        .map(|dt| {
            let l: DateTime<Local> = dt.with_timezone(&Local);
            l.format("%H:%M").to_string()
        })
        .unwrap_or_else(|| "??".to_string());

    let mut lines = vec![i18n::digest_next_shift(&local, location_name)];
    let mut has_entries = false;
    if let Some(entries) = shift.get("entries").and_then(|v| v.as_array()) {
        for entry in entries {
            let kind = entry
                .get("type")
                .and_then(|t| t.get("name"))
                .and_then(|n| n.as_str())
                .unwrap_or("?");
            if let Some(users) = entry.get("users").and_then(|u| u.as_array()) {
                for user in users {
                    let name = user.get("name").and_then(|n| n.as_str()).unwrap_or("?");
                    lines.push(format!("- {} [{}]", name, kind));
                    has_entries = true;
                }
            }
        }
    }
    if !has_entries {
        lines.push(i18n::DIGEST_NO_ENTRIES.to_string());
    }
    lines.join("\n")
}

/// One pass of the digest. Returns the number of new shifts announced.
/// `announced` is mutated in place so the caller (the loop) can keep
/// state across passes.
#[allow(clippy::too_many_arguments)]
pub async fn digest_once(
    outbox: &mut Outbox,
    pool: &SqlitePool,
    config: &AppConfig,
    client: &EngelsystemClient,
    announced: &mut HashSet<i64>,
    now: NaiveDateTime,
) -> anyhow::Result<usize> {
    let lookahead = Duration::minutes(config.shift_digest.lookahead_minutes as i64);
    let now_utc = Utc.from_utc_datetime(&now);
    let cutoff = now_utc + lookahead;
    let helfer_orga = config.route_category("Helfer").to_string();
    let mut new_count = 0;

    for (location_name, location_id) in &config.locations {
        let shifts = match client.shifts_at(*location_id).await {
            Ok(s) => s,
            Err(e) => {
                tracing::warn!(
                    "digest: shift fetch for {:?} (id={}) failed: {}",
                    location_name,
                    location_id,
                    e
                );
                continue;
            }
        };
        for shift in shifts {
            let Some(id) = shift.get("id").and_then(|v| v.as_i64()) else {
                continue;
            };
            if announced.contains(&id) {
                continue;
            }
            let Some(start) = shift
                .get("starts_at")
                .and_then(|v| v.as_str())
                .and_then(parse_iso)
            else {
                continue;
            };
            let start_utc = start.with_timezone(&Utc);
            if !(now_utc <= start_utc && start_utc < cutoff) {
                continue;
            }
            let body = format_shift_announcement(&shift, location_name);
            notify::group_msg(outbox, pool, &helfer_orga, &body, None).await?;
            announced.insert(id);
            new_count += 1;
        }
    }
    Ok(new_count)
}

/// Long-running loop. Cancellation drops out cleanly via the await on
/// `tokio::time::sleep`.
#[allow(dead_code)]
pub async fn shift_digest_loop(
    pool: SqlitePool,
    config: AppConfig,
    client: EngelsystemClient,
) -> anyhow::Result<()> {
    let sd = &config.shift_digest;
    if !sd.enabled {
        tracing::info!("shift digest disabled in config");
        return Ok(());
    }
    tracing::info!(
        "shift digest active: window {}–{} local, every {} min, lookahead {} min",
        sd.window_start,
        sd.window_end,
        sd.check_interval_minutes,
        sd.lookahead_minutes
    );
    let interval = std::time::Duration::from_secs(sd.check_interval_minutes * 60);
    let mut announced: HashSet<i64> = HashSet::new();
    loop {
        let now = now_utc();
        let now_local = Utc.from_utc_datetime(&now).with_timezone(&Local).time();
        if is_within_window(now_local, sd.window_start, sd.window_end) {
            let mut outbox = Outbox::new();
            if let Err(e) =
                digest_once(&mut outbox, &pool, &config, &client, &mut announced, now).await
            {
                tracing::warn!("digest pass failed: {}", e);
            }
            // In the loop driver we don't have a Bot to consume the
            // outbox; the teloxide adapter wraps this fn and flushes.
            // Tests construct the outbox themselves and call digest_once.
            // For now, log if a non-empty outbox slipped through.
            if !outbox.actions.is_empty() {
                tracing::trace!("digest produced {} actions", outbox.actions.len());
            }
        }
        tokio::time::sleep(interval).await;
    }
}
