//! FastAPI-equivalent dashboard endpoint plus SSE stream. The wire
//! contract matches the Python implementation exactly: `/api/tickets`,
//! `/api/stream`, `/api/health`, and static files mounted at root. SSE
//! events carry the same JSON shape that the Python `Ticket.model_dump_json`
//! produces, so a browser can reach for either backend.

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Json};
use axum::routing::get;
use axum::Router;
use futures_util::stream::Stream;
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;
use std::convert::Infallible;
use std::sync::Arc;
use tokio_stream::StreamExt;
use tower_http::services::ServeDir;

use crate::events::EventBus;
use crate::models::Ticket;
use crate::repo;

#[derive(Clone)]
pub struct AppState {
    pub pool: SqlitePool,
    pub events: EventBus,
}

#[derive(Debug, Deserialize)]
pub struct GroupFilter {
    group: Option<String>,
}

#[derive(Debug, Serialize)]
struct Health {
    ok: bool,
    subscribers: usize,
}

/// Mirrors the Python `_matches_group`: case-insensitive equality on
/// the `group_tasked` field, with `None` meaning "no filter".
pub fn matches_group(payload_json: &str, group: Option<&str>) -> bool {
    let Some(group) = group else { return true };
    let Ok(parsed) = serde_json::from_str::<serde_json::Value>(payload_json) else {
        return false;
    };
    let Some(gt) = parsed.get("group_tasked").and_then(|v| v.as_str()) else {
        return false;
    };
    gt.eq_ignore_ascii_case(group)
}

pub fn build_app(state: AppState, static_dir: impl Into<std::path::PathBuf>) -> Router {
    let static_dir = static_dir.into();
    Router::new()
        .route("/api/tickets", get(snapshot))
        .route("/api/stream", get(stream))
        .route("/api/health", get(health))
        .fallback_service(ServeDir::new(static_dir).append_index_html_on_directories(true))
        .with_state(Arc::new(state))
}

async fn snapshot(
    State(state): State<Arc<AppState>>,
    Query(q): Query<GroupFilter>,
) -> Result<Json<Vec<Ticket>>, StatusCode> {
    let tickets = repo::active_tickets(&state.pool, None, None)
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let filtered: Vec<Ticket> = match q.group.as_deref() {
        Some(g) => tickets
            .into_iter()
            .filter(|t| t.group_tasked.eq_ignore_ascii_case(g))
            .collect(),
        None => tickets,
    };
    Ok(Json(filtered))
}

async fn stream(
    State(state): State<Arc<AppState>>,
    Query(q): Query<GroupFilter>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let group = q.group;
    let s = state.events.subscribe().filter_map(move |payload| {
        if matches_group(&payload, group.as_deref()) {
            Some(Ok(Event::default().event("ticket").data(payload)))
        } else {
            None
        }
    });
    Sse::new(s).keep_alive(KeepAlive::default())
}

async fn health(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    Json(Health {
        ok: true,
        subscribers: state.events.subscriber_count(),
    })
}
