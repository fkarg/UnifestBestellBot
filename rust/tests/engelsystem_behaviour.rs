//! Behavioural tests for Engelsystem integration. The summary renderer
//! is exercised against the shared fixture (`tests/fixtures/engelsystem_shifts.json`,
//! identical to the Python side). The HTTP client is exercised against
//! a wiremock-backed server.

mod common;

use chrono::{Duration, NaiveDate, NaiveDateTime};
use unifestbestellbot::engelsystem::{lookup_for_group, summarize_shifts, EngelsystemClient};

fn load_fixture() -> Vec<serde_json::Value> {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/engelsystem_shifts.json");
    let text = std::fs::read_to_string(path).expect("fixture");
    let value: serde_json::Value = serde_json::from_str(&text).expect("json");
    value["data"].as_array().expect("data array").clone()
}

fn at(date: NaiveDate, h: u32, m: u32) -> NaiveDateTime {
    date.and_hms_opt(h, m, 0).expect("hms")
}

#[test]
fn summary_with_current_shift() {
    let shifts = load_fixture();
    let now = at(NaiveDate::from_ymd_opt(2026, 5, 22).unwrap(), 15, 0);
    let out = summarize_shifts(&shifts, now, Duration::minutes(20));
    assert!(out.contains("Momentane Schicht"));
    assert!(out.contains("Alice [Bar]"));
    assert!(out.contains("Carol [Kasse]"));
    // Next shift starts at 16:00; that's 1h away — beyond the 20m window.
    assert!(!out.contains("Nächste Schicht"));
}

#[test]
fn summary_with_imminent_next_shift() {
    let shifts = load_fixture();
    // 15:50: the 16:00 shift is 10m away — inside the 20m window.
    let now = at(NaiveDate::from_ymd_opt(2026, 5, 22).unwrap(), 15, 50);
    let out = summarize_shifts(&shifts, now, Duration::minutes(20));
    assert!(out.contains("Momentane Schicht"));
    assert!(out.contains("Nächste Schicht in 10m"));
    assert!(out.contains("Dan [Bar]"));
}

#[test]
fn summary_empty_when_no_running_or_imminent() {
    let shifts = load_fixture();
    let now = at(NaiveDate::from_ymd_opt(2026, 5, 22).unwrap(), 19, 0);
    let out = summarize_shifts(&shifts, now, Duration::minutes(20));
    assert!(out.contains("Keine aktuellen oder bevorstehenden"));
}

#[test]
fn summary_renders_multi_hour_remaining_time() {
    let shifts: Vec<serde_json::Value> = serde_json::from_str(
        r#"[{
            "starts_at": "2026-05-22T14:00:00+00:00",
            "ends_at":   "2026-05-22T18:00:00+00:00",
            "entries": []
        }]"#,
    )
    .unwrap();
    let now = at(NaiveDate::from_ymd_opt(2026, 5, 22).unwrap(), 14, 30);
    let out = summarize_shifts(&shifts, now, Duration::minutes(20));
    assert!(out.contains("3h 30m"));
}

#[tokio::test]
async fn lookup_for_unknown_location_returns_german_fallback() {
    // Tickets is at Eingang, which the test config doesn't list under
    // `locations:` — so lookup should bail with the configured-message.
    let client = EngelsystemClient::new("http://invalid.example", "k");
    let out = lookup_for_group(&client, &common::test_config(), "Tickets").await;
    assert!(out.contains("nicht korrekt konfiguriert") || out.contains("keine Schichten"));
}

// --- HTTP behaviour via wiremock -----------------------------------------

#[tokio::test]
async fn http_lookup_returns_summary_against_mock_server() {
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    let server = MockServer::start().await;
    let fixture = serde_json::json!({
        "data": [{
            "id": 1,
            "starts_at": "2026-05-22T14:00:00+00:00",
            "ends_at":   "2026-05-22T16:00:00+00:00",
            "entries": [
                {"type": {"name": "Bar"}, "users": [{"name": "Alice"}]}
            ]
        }]
    });
    Mock::given(method("GET"))
        .and(path("/locations/12/shifts"))
        .and(header("x-api-key", "test-key"))
        .respond_with(ResponseTemplate::new(200).set_body_json(fixture))
        .mount(&server)
        .await;

    let client = EngelsystemClient::new(server.uri(), "test-key");
    let shifts = client.shifts_at(12).await.unwrap();
    assert_eq!(shifts.len(), 1);
    assert_eq!(shifts[0]["entries"][0]["users"][0]["name"], "Alice");
}

#[tokio::test]
async fn http_failure_surfaces_as_fallback_string_in_lookup() {
    // Point the client at an address nothing is listening on. The 5s
    // timeout we set in the client trips quickly when the connect fails.
    let client = EngelsystemClient::new("http://127.0.0.1:1/", "k");
    // Force the lookup to attempt an HTTP call by registering the
    // location_id in a custom config.
    let yaml = r#"
stalls:
  - name: "X"
    location: "Innenhof"
    type: "Cocktail"
orga_groups:
  - name: "Z"
    categories: ["x"]
    default: true
locations:
  "Innenhof": 12
"#;
    let cfg: unifestbestellbot::config::AppConfig = serde_yaml::from_str(yaml).unwrap();
    cfg.validate().unwrap();
    let out = lookup_for_group(&client, &cfg, "X").await;
    assert!(out.contains("fehlgeschlagen"));
}
