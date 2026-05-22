//! Behavioural tests for the FastAPI-equivalent dashboard endpoints.
//! The HTTP layer is exercised by binding to an ephemeral port and
//! issuing real requests via `reqwest`.

mod common;

use unifestbestellbot::db::test_pool;
use unifestbestellbot::events::EventBus;
use unifestbestellbot::models::{Ticket, TicketStatus};
use unifestbestellbot::repo;
use unifestbestellbot::web::{build_app, matches_group, AppState};

async fn spawn_server(state: AppState) -> String {
    let static_dir =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/static");
    let app = build_app(state, static_dir);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("http://{}", addr)
}

#[tokio::test]
async fn snapshot_returns_active_tickets() {
    let pool = test_pool().await;
    let events = EventBus::new();
    common::open_ticket(&pool, "a", "Cocktailbar 1", "Finanz").await;
    common::open_ticket(&pool, "b", "Cocktailbar 1", "Finanz").await;

    let base = spawn_server(AppState { pool: pool.clone(), events }).await;
    let r = reqwest::get(format!("{}/api/tickets", base)).await.unwrap();
    assert_eq!(r.status(), 200);
    let tickets: Vec<Ticket> = r.json().await.unwrap();
    let texts: std::collections::HashSet<_> = tickets.iter().map(|t| t.text.clone()).collect();
    assert!(texts.contains("a"));
    assert!(texts.contains("b"));
}

#[tokio::test]
async fn snapshot_filters_by_group_case_insensitively() {
    let pool = test_pool().await;
    let events = EventBus::new();
    common::open_ticket(&pool, "finanz", "X", "Finanz").await;
    common::open_ticket(&pool, "bimi", "X", "BiMi").await;

    let base = spawn_server(AppState { pool: pool.clone(), events }).await;
    let r = reqwest::get(format!("{}/api/tickets?group=finanz", base))
        .await
        .unwrap();
    let tickets: Vec<Ticket> = r.json().await.unwrap();
    assert_eq!(tickets.len(), 1);
    assert_eq!(tickets[0].text, "finanz");
}

#[tokio::test]
async fn snapshot_excludes_closed_tickets() {
    let pool = test_pool().await;
    let events = EventBus::new();
    let t = common::open_ticket(&pool, "will close", "X", "Finanz").await;
    repo::close_ticket(&pool, t.id, 1).await.unwrap();

    let base = spawn_server(AppState { pool: pool.clone(), events }).await;
    let r = reqwest::get(format!("{}/api/tickets", base)).await.unwrap();
    let tickets: Vec<Ticket> = r.json().await.unwrap();
    assert!(tickets.is_empty());
}

#[tokio::test]
async fn health_endpoint_returns_subscriber_count() {
    let pool = test_pool().await;
    let events = EventBus::new();
    let base = spawn_server(AppState { pool, events }).await;
    let r = reqwest::get(format!("{}/api/health", base)).await.unwrap();
    let body: serde_json::Value = r.json().await.unwrap();
    assert_eq!(body["ok"], true);
    assert!(body["subscribers"].is_number());
}

#[tokio::test]
async fn root_serves_index_html() {
    let pool = test_pool().await;
    let events = EventBus::new();
    let base = spawn_server(AppState { pool, events }).await;
    let r = reqwest::get(&base).await.unwrap();
    assert_eq!(r.status(), 200);
    let body = r.text().await.unwrap();
    assert!(body.contains("UnifestBestellBot"));
}

#[tokio::test]
async fn main_js_is_served_with_expected_content() {
    let pool = test_pool().await;
    let events = EventBus::new();
    let base = spawn_server(AppState { pool, events }).await;
    let r = reqwest::get(format!("{}/main.js", base)).await.unwrap();
    assert_eq!(r.status(), 200);
    assert!(r.text().await.unwrap().contains("EventSource"));
}

// --- EventBus broadcast --------------------------------------------------

#[tokio::test]
async fn event_bus_delivers_published_payload_to_subscriber() {
    use tokio_stream::StreamExt;

    let bus = EventBus::new();
    let mut stream = Box::pin(bus.subscribe());
    // Let the subscription attach.
    tokio::task::yield_now().await;

    let ticket = Ticket {
        id: 1,
        status: TicketStatus::Open,
        category: "Geld".into(),
        text: "x".into(),
        group_requesting: "Cocktailbar 1".into(),
        group_tasked: "Finanz".into(),
        who_wip: None,
        created_at: unifestbestellbot::models::now_utc(),
        closed_at: None,
    };
    bus.publish_ticket(&ticket);

    let payload = tokio::time::timeout(std::time::Duration::from_secs(1), stream.next())
        .await
        .expect("not timed out")
        .expect("payload");
    let parsed: serde_json::Value = serde_json::from_str(&payload).unwrap();
    assert_eq!(parsed["text"], "x");
    assert_eq!(parsed["group_tasked"], "Finanz");
}

#[tokio::test]
async fn event_bus_drops_quietly_when_no_subscribers() {
    let bus = EventBus::new();
    let ticket = Ticket {
        id: 1,
        status: TicketStatus::Open,
        category: "Geld".into(),
        text: "x".into(),
        group_requesting: "A".into(),
        group_tasked: "B".into(),
        who_wip: None,
        created_at: unifestbestellbot::models::now_utc(),
        closed_at: None,
    };
    // Doesn't panic, doesn't return an error to the caller.
    bus.publish_ticket(&ticket);
    assert_eq!(bus.subscriber_count(), 0);
}

// --- matches_group helper -----------------------------------------------

#[test]
fn matches_group_none_passes_through() {
    assert!(matches_group(r#"{"group_tasked":"Finanz"}"#, None));
}

#[test]
fn matches_group_case_insensitive_match() {
    assert!(matches_group(r#"{"group_tasked":"Finanz"}"#, Some("finanz")));
}

#[test]
fn matches_group_mismatch_filters_out() {
    assert!(!matches_group(
        r#"{"group_tasked":"Finanz"}"#,
        Some("BiMi")
    ));
}

#[test]
fn matches_group_invalid_json_filters_out() {
    assert!(!matches_group("not json", Some("Finanz")));
}
