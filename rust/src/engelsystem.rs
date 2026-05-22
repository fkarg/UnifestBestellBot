//! Engelsystem shift lookup. Identical wire contract to the Python
//! `engelsystem.py`: the same JSON response shape, the same German
//! summary format, the same fallback messages on missing config or
//! HTTP errors.

use chrono::{DateTime, Duration, FixedOffset, NaiveDateTime, TimeZone, Utc};
use serde::Deserialize;

use crate::config::AppConfig;
use crate::i18n;

#[derive(Debug, Clone)]
pub struct EngelsystemClient {
    http: reqwest::Client,
    base_url: String,
    api_key: String,
}

#[derive(Debug, Deserialize)]
struct ShiftsEnvelope {
    data: Vec<serde_json::Value>,
}

impl EngelsystemClient {
    pub fn new(base_url: impl Into<String>, api_key: impl Into<String>) -> Self {
        let http = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .expect("reqwest client");
        Self {
            http,
            base_url: base_url.into(),
            api_key: api_key.into(),
        }
    }

    /// Used by tests to swap in a wiremock-backed base URL.
    pub fn with_base_url(base_url: impl Into<String>, api_key: impl Into<String>) -> Self {
        Self::new(base_url, api_key)
    }

    pub async fn shifts_at(&self, location_id: i32) -> anyhow::Result<Vec<serde_json::Value>> {
        let base = self.base_url.trim_end_matches('/');
        let url = format!("{}/locations/{}/shifts", base, location_id);
        let resp = self
            .http
            .get(&url)
            .header("Accept", "application/json")
            .header("x-api-key", &self.api_key)
            .send()
            .await?;
        let resp = resp.error_for_status()?;
        let env: ShiftsEnvelope = resp.json().await?;
        Ok(env.data)
    }
}

fn fmt_delta(d: Duration) -> String {
    let total = d.num_seconds().max(0);
    let h = total / 3600;
    let m = (total % 3600) / 60;
    if h > 0 {
        format!("{}h {}m", h, m)
    } else {
        format!("{}m", m)
    }
}

fn parse_iso(s: &str) -> Option<DateTime<FixedOffset>> {
    DateTime::parse_from_rfc3339(s).ok()
}

/// Pure rendering. Takes the Engelsystem `data` array and a deterministic
/// `now` (UTC) so it can be unit-tested with fixtures.
pub fn summarize_shifts(
    shifts: &[serde_json::Value],
    now: NaiveDateTime,
    next_window: Duration,
) -> String {
    let now_utc = Utc.from_utc_datetime(&now);
    let mut current: Vec<&serde_json::Value> = Vec::new();
    let mut upcoming: Vec<&serde_json::Value> = Vec::new();

    for s in shifts {
        let Some(start_s) = s.get("starts_at").and_then(|v| v.as_str()) else {
            continue;
        };
        let Some(end_s) = s.get("ends_at").and_then(|v| v.as_str()) else {
            continue;
        };
        let Some(start) = parse_iso(start_s) else { continue };
        let Some(end) = parse_iso(end_s) else { continue };

        if start.with_timezone(&Utc) <= now_utc && now_utc < end.with_timezone(&Utc) {
            current.push(s);
        } else if now_utc < start.with_timezone(&Utc)
            && start.with_timezone(&Utc) <= now_utc + next_window
        {
            upcoming.push(s);
        }
    }

    let mut lines: Vec<String> = Vec::new();

    for shift in &current {
        let end = shift
            .get("ends_at")
            .and_then(|v| v.as_str())
            .and_then(parse_iso)
            .map(|t| t.with_timezone(&Utc) - now_utc)
            .unwrap_or_else(Duration::zero);
        lines.push(format!("Momentane Schicht noch {}:", fmt_delta(end)));
        for entry in entries(shift) {
            lines.push(entry);
        }
        lines.push(String::new());
    }

    for shift in &upcoming {
        let start = shift
            .get("starts_at")
            .and_then(|v| v.as_str())
            .and_then(parse_iso)
            .map(|t| t.with_timezone(&Utc) - now_utc)
            .unwrap_or_else(Duration::zero);
        lines.push(format!("Nächste Schicht in {}:", fmt_delta(start)));
        for entry in entries(shift) {
            lines.push(entry);
        }
        lines.push(String::new());
    }

    if lines.is_empty() {
        return i18n::ENGELSYSTEM_NO_SHIFTS.to_string();
    }

    while lines.last().map(|s| s.is_empty()).unwrap_or(false) {
        lines.pop();
    }
    lines.join("\n")
}

fn entries(shift: &serde_json::Value) -> Vec<String> {
    let mut out = Vec::new();
    let Some(entries) = shift.get("entries").and_then(|v| v.as_array()) else {
        return out;
    };
    for entry in entries {
        let kind = entry
            .get("type")
            .and_then(|t| t.get("name"))
            .and_then(|n| n.as_str())
            .unwrap_or("?");
        let Some(users) = entry.get("users").and_then(|u| u.as_array()) else {
            continue;
        };
        for user in users {
            let name = user.get("name").and_then(|n| n.as_str()).unwrap_or("?");
            out.push(format!("- {} [{}]", name, kind));
        }
    }
    out
}

/// Composite: look up the stand's Engelsystem location id, fetch its
/// shifts, summarize. Returns the German fallback strings on missing
/// config or HTTP errors so the handler never has to format errors
/// itself.
pub async fn lookup_for_group(
    client: &EngelsystemClient,
    config: &AppConfig,
    group: &str,
) -> String {
    let Some(loc_id) = config.location_id_for_group(group) else {
        return i18n::ENGELSYSTEM_NOT_CONFIGURED.to_string();
    };
    let shifts = match client.shifts_at(loc_id).await {
        Ok(s) => s,
        Err(e) => {
            tracing::warn!("engelsystem fetch failed: {}", e);
            return i18n::ENGELSYSTEM_LOOKUP_FAILED.to_string();
        }
    };
    summarize_shifts(&shifts, crate::models::now_utc(), Duration::minutes(20))
}
