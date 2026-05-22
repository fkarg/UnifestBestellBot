//! Behavioural tests for the Engelsystem shift digest. Drives
//! `digest_once` against a wiremock-backed Engelsystem and asserts on
//! the outbox + the `announced` set.

mod common;

use std::collections::HashSet;

use chrono::{NaiveDate, NaiveTime};
use unifestbestellbot::bot::digest::{digest_once, is_within_window};
use unifestbestellbot::bot::Outbox;
use unifestbestellbot::config::AppConfig;
use unifestbestellbot::db::test_pool;
use unifestbestellbot::engelsystem::EngelsystemClient;
use unifestbestellbot::models::Registration;
use unifestbestellbot::repo;

fn t(h: u32, m: u32) -> NaiveTime {
    NaiveTime::from_hms_opt(h, m, 0).unwrap()
}

// --- is_within_window ----------------------------------------------------

#[test]
fn window_within_same_day() {
    let start = t(9, 0);
    let end = t(17, 0);
    assert!(is_within_window(t(12, 0), start, end));
    assert!(!is_within_window(t(8, 0), start, end));
    // exclusive end
    assert!(!is_within_window(t(17, 0), start, end));
}

#[test]
fn window_wraps_midnight() {
    let start = t(18, 0);
    let end = t(2, 0);
    assert!(is_within_window(t(20, 0), start, end));
    assert!(is_within_window(t(1, 0), start, end));
    assert!(!is_within_window(t(3, 0), start, end));
    assert!(!is_within_window(t(17, 59), start, end));
}

#[test]
fn window_equal_start_end_is_always_on() {
    let z = t(0, 0);
    assert!(is_within_window(t(7, 0), z, z));
    assert!(is_within_window(t(23, 59), z, z));
}

// --- digest_once --------------------------------------------------------

fn digest_config() -> AppConfig {
    let yaml = r#"
stalls:
  - name: "Crew A"
    location: "Forum Süd"
    type: "Cocktail"
orga_groups:
  - name: "Helfen"
    categories: ["Helfer"]
  - name: "Zentrale"
    categories: ["Sonstiges"]
    default: true
locations:
  "Forum Süd": 12
shift_digest:
  enabled: true
  window_start: "18:00:00"
  window_end: "02:00:00"
  check_interval_minutes: 5
  lookahead_minutes: 10
"#;
    let cfg: AppConfig = serde_yaml::from_str(yaml).unwrap();
    cfg.validate().unwrap();
    cfg
}

async fn mock_with_shift(server: &wiremock::MockServer, path: &str, json: serde_json::Value) {
    use wiremock::matchers::method;
    use wiremock::matchers::path as path_matcher;
    use wiremock::{Mock, ResponseTemplate};
    Mock::given(method("GET"))
        .and(path_matcher(path.to_string()))
        .respond_with(ResponseTemplate::new(200).set_body_json(json))
        .mount(server)
        .await;
}

#[tokio::test]
async fn digest_announces_shift_in_lookahead_window() {
    let server = wiremock::MockServer::start().await;
    mock_with_shift(
        &server,
        "/locations/12/shifts",
        serde_json::json!({
            "data": [{
                "id": 1,
                "starts_at": "2026-05-22T16:05:00+00:00",
                "ends_at":   "2026-05-22T18:05:00+00:00",
                "entries": [
                    {"type": {"name": "Bar"}, "users": [{"name": "Alice"}]}
                ]
            }]
        }),
    )
    .await;
    let client = EngelsystemClient::with_base_url(server.uri(), "test");
    let cfg = digest_config();
    let pool = test_pool().await;
    repo::upsert_registration(&pool, &Registration::new(7, "Helfen"))
        .await
        .unwrap();

    let now = NaiveDate::from_ymd_opt(2026, 5, 22)
        .unwrap()
        .and_hms_opt(16, 0, 0)
        .unwrap();
    let mut announced = HashSet::new();
    let mut outbox = Outbox::new();
    let new_count = digest_once(&mut outbox, &pool, &cfg, &client, &mut announced, now)
        .await
        .unwrap();

    assert_eq!(new_count, 1);
    assert!(announced.contains(&1));
    let dms = outbox.dms();
    assert!(dms.iter().any(|(c, t)| **c == 7 && t.contains("Alice")));
}

#[tokio::test]
async fn digest_skips_shifts_outside_window() {
    let server = wiremock::MockServer::start().await;
    mock_with_shift(
        &server,
        "/locations/12/shifts",
        serde_json::json!({
            "data": [{
                "id": 1,
                "starts_at": "2026-05-22T16:30:00+00:00",
                "ends_at":   "2026-05-22T18:30:00+00:00",
                "entries": []
            }]
        }),
    )
    .await;
    let client = EngelsystemClient::with_base_url(server.uri(), "test");
    let cfg = digest_config();
    let pool = test_pool().await;

    let now = NaiveDate::from_ymd_opt(2026, 5, 22)
        .unwrap()
        .and_hms_opt(16, 0, 0)
        .unwrap();
    let mut announced = HashSet::new();
    let mut outbox = Outbox::new();
    let new_count = digest_once(&mut outbox, &pool, &cfg, &client, &mut announced, now)
        .await
        .unwrap();
    assert_eq!(new_count, 0);
    assert!(outbox.dms().is_empty());
}

#[tokio::test]
async fn digest_does_not_reannounce_known_shift() {
    let server = wiremock::MockServer::start().await;
    mock_with_shift(
        &server,
        "/locations/12/shifts",
        serde_json::json!({
            "data": [{
                "id": 1,
                "starts_at": "2026-05-22T16:05:00+00:00",
                "ends_at":   "2026-05-22T18:05:00+00:00",
                "entries": [{"type": {"name": "Bar"}, "users": [{"name": "Alice"}]}]
            }]
        }),
    )
    .await;
    let client = EngelsystemClient::with_base_url(server.uri(), "test");
    let cfg = digest_config();
    let pool = test_pool().await;
    repo::upsert_registration(&pool, &Registration::new(7, "Helfen"))
        .await
        .unwrap();

    let now = NaiveDate::from_ymd_opt(2026, 5, 22)
        .unwrap()
        .and_hms_opt(16, 0, 0)
        .unwrap();
    let mut announced: HashSet<i64> = HashSet::from([1]);
    let mut outbox = Outbox::new();
    let new_count = digest_once(&mut outbox, &pool, &cfg, &client, &mut announced, now)
        .await
        .unwrap();
    assert_eq!(new_count, 0);
    assert!(outbox.dms().is_empty());
}

#[tokio::test]
async fn digest_survives_http_failure() {
    // No mock mounted — wiremock returns 404 for every request.
    let server = wiremock::MockServer::start().await;
    let client = EngelsystemClient::with_base_url(server.uri(), "test");
    let cfg = digest_config();
    let pool = test_pool().await;
    let now = NaiveDate::from_ymd_opt(2026, 5, 22)
        .unwrap()
        .and_hms_opt(16, 0, 0)
        .unwrap();
    let mut announced = HashSet::new();
    let mut outbox = Outbox::new();
    // Should not panic, returns 0 newly announced.
    let new_count = digest_once(&mut outbox, &pool, &cfg, &client, &mut announced, now)
        .await
        .unwrap();
    assert_eq!(new_count, 0);
}

#[tokio::test]
async fn digest_routes_to_renamed_helfer_handler() {
    let yaml = r#"
stalls:
  - name: "Crew A"
    location: "X"
    type: "Cocktail"
orga_groups:
  - name: "Volunteer-Crew"
    categories: ["Helfer"]
  - name: "Zentrale"
    categories: ["Sonstiges"]
    default: true
locations:
  "X": 12
shift_digest:
  enabled: true
"#;
    let cfg: AppConfig = serde_yaml::from_str(yaml).unwrap();
    cfg.validate().unwrap();

    let server = wiremock::MockServer::start().await;
    mock_with_shift(
        &server,
        "/locations/12/shifts",
        serde_json::json!({
            "data": [{
                "id": 99,
                "starts_at": "2026-05-22T16:05:00+00:00",
                "ends_at":   "2026-05-22T18:05:00+00:00",
                "entries": []
            }]
        }),
    )
    .await;
    let client = EngelsystemClient::with_base_url(server.uri(), "test");
    let pool = test_pool().await;
    repo::upsert_registration(&pool, &Registration::new(8, "Volunteer-Crew"))
        .await
        .unwrap();

    let now = NaiveDate::from_ymd_opt(2026, 5, 22)
        .unwrap()
        .and_hms_opt(16, 0, 0)
        .unwrap();
    let mut outbox = Outbox::new();
    let _ = digest_once(&mut outbox, &pool, &cfg, &client, &mut HashSet::new(), now)
        .await
        .unwrap();
    let recipients: Vec<i64> = outbox.dms().iter().map(|(c, _)| **c).collect();
    assert!(recipients.contains(&8));
}
