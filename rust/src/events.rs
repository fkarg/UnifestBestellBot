//! In-process pub/sub bus for ticket updates. Mirrors the Python
//! `events.EventBus` but uses `tokio::sync::broadcast` so subscribers
//! that fall behind get dropped naturally via `Err(Lagged)` and
//! shutdown is a single `drop` of the sender.

use crate::models::Ticket;
use tokio::sync::broadcast;
use tokio_stream::{wrappers::BroadcastStream, Stream, StreamExt};

const DEFAULT_CHANNEL_CAPACITY: usize = 128;

#[derive(Clone)]
pub struct EventBus {
    tx: broadcast::Sender<String>,
}

impl EventBus {
    pub fn new() -> Self {
        Self::with_capacity(DEFAULT_CHANNEL_CAPACITY)
    }

    pub fn with_capacity(capacity: usize) -> Self {
        let (tx, _rx) = broadcast::channel(capacity);
        Self { tx }
    }

    pub fn subscriber_count(&self) -> usize {
        self.tx.receiver_count()
    }

    /// Publish one ticket. Serialised once and broadcast to every
    /// subscriber. Silent no-op when no subscribers are attached
    /// (broadcast returns `Err(NoReceivers)` which we discard).
    pub fn publish_ticket(&self, ticket: &Ticket) {
        let payload = match serde_json::to_string(ticket) {
            Ok(s) => s,
            Err(e) => {
                tracing::error!("event payload serialize failed: {}", e);
                return;
            }
        };
        let _ = self.tx.send(payload);
    }

    /// Yields ticket payloads (as JSON strings) until either the bus is
    /// closed or the subscriber falls so far behind that the channel
    /// laps it. Slow subscribers reconnect via EventSource on the
    /// browser side and pull a fresh snapshot.
    pub fn subscribe(&self) -> impl Stream<Item = String> + Send + 'static {
        let rx = self.tx.subscribe();
        BroadcastStream::new(rx).filter_map(|res| res.ok())
    }
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new()
    }
}
