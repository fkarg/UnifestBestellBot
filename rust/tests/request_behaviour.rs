//! Behavioural tests for the /request FSM. Drives the state machine
//! one step at a time and asserts the final ticket lands with the
//! right routing and text shape.

mod common;

use unifestbestellbot::bot::{request as flow, request::RequestState, Caller, Outbox};
use unifestbestellbot::db::test_pool;
use unifestbestellbot::events::EventBus;
use unifestbestellbot::models::Registration;
use unifestbestellbot::repo;

fn alice() -> Caller {
    Caller {
        chat_id: 1,
        username: Some("alice".into()),
        first_name: Some("Alice".into()),
        last_name: None,
    }
}

async fn registered_at(pool: &sqlx::SqlitePool, group: &str) {
    repo::upsert_registration(pool, &Registration::new(1, group))
        .await
        .unwrap();
}

// --- Entry / cancel / in-progress ---------------------------------------

#[tokio::test]
async fn request_without_registration_prompts_to_register() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    let state = flow::cmd_request(&mut outbox, &pool, &cfg, &alice(), RequestState::Idle)
        .await
        .unwrap();
    assert_eq!(state, RequestState::Idle);
    assert!(outbox.reply_texts()[0].contains("/register"));
}

#[tokio::test]
async fn request_starts_at_category_when_registered() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut outbox = Outbox::new();
    let state = flow::cmd_request(&mut outbox, &pool, &cfg, &alice(), RequestState::Idle)
        .await
        .unwrap();
    assert_eq!(
        state,
        RequestState::Category {
            group: "Cocktailbar 1".into()
        }
    );
}

#[tokio::test]
async fn request_in_progress_does_not_overwrite_state() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut outbox = Outbox::new();
    let initial = RequestState::Money {
        group: "Cocktailbar 1".into(),
        category: "Geld".into(),
    };
    let state =
        flow::cmd_request(&mut outbox, &pool, &cfg, &alice(), initial.clone())
            .await
            .unwrap();
    assert_eq!(state, initial);
    assert!(outbox.reply_texts()[0].contains("noch nicht abgeschlossen"));
}

#[tokio::test]
async fn cancel_clears_state() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut outbox = Outbox::new();
    let state = flow::cmd_cancel(
        &mut outbox,
        &pool,
        &cfg,
        &alice(),
        RequestState::Money {
            group: "Cocktailbar 1".into(),
            category: "Geld".into(),
        },
    )
    .await
    .unwrap();
    assert_eq!(state, RequestState::Idle);
}

// --- End-to-end per category --------------------------------------------

async fn drive(
    pool: &sqlx::SqlitePool,
    cfg: &unifestbestellbot::config::AppConfig,
    bus: &EventBus,
    state: RequestState,
    text: &str,
) -> (Outbox, RequestState) {
    let mut outbox = Outbox::new();
    let state = flow::on_text(
        &mut outbox,
        pool,
        cfg,
        bus,
        None, // no engelsystem in unit tests; helper path tests it
        &alice(),
        state,
        text,
    )
    .await
    .unwrap();
    (outbox, state)
}

#[tokio::test]
async fn geld_wechselgeld_muenzen_routes_to_finanz() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;

    let mut state = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s) = drive(&pool, &cfg, &bus, state, "Geld").await;
    state = s;
    assert!(matches!(state, RequestState::Money { .. }));

    let (_, s) = drive(&pool, &cfg, &bus, state, "Wechselgeld").await;
    state = s;
    assert!(matches!(state, RequestState::MoneyChange { .. }));

    let (outbox, s) = drive(&pool, &cfg, &bus, state, "Münzen").await;
    assert_eq!(s, RequestState::Idle);

    let tickets = repo::active_tickets(&pool, Some("Finanz"), None).await.unwrap();
    assert_eq!(tickets.len(), 1);
    let text = &tickets[0].text;
    assert!(text.contains("Münzen"));
    assert!(text.contains("Innenhof [Cocktail]")); // BiMi-style display, no team name
    // The user got a confirmation naming the orga group.
    let replies = outbox.reply_texts();
    assert!(replies.iter().any(|r| r.contains("[Finanz]")));
}

#[tokio::test]
async fn geld_abholen_routes_to_finanz_as_collection() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Geld").await;
    s = s2;
    let (_, s3) = drive(&pool, &cfg, &bus, s, "Geld Abholen").await;
    assert_eq!(s3, RequestState::Idle);
    let t = &repo::active_tickets(&pool, Some("Finanz"), None).await.unwrap()[0];
    assert!(t.text.contains("Geld abholen"));
}

#[tokio::test]
async fn becher_normal_with_amount_routes_to_bimi() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Becher").await;
    s = s2;
    let (_, s3) = drive(&pool, &cfg, &bus, s, "Normale Becher").await;
    s = s3;
    assert!(matches!(s, RequestState::Amount { .. }));
    let (_, s4) = drive(&pool, &cfg, &bus, s, "~20").await;
    assert_eq!(s4, RequestState::Idle);
    let t = &repo::active_tickets(&pool, Some("BiMi"), None).await.unwrap()[0];
    assert!(t.text.contains("Normale Becher"));
    assert!(t.text.contains("~20"));
}

#[tokio::test]
async fn becher_dirty_collect_routes_to_bimi() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Becher").await;
    s = s2;
    let (_, s3) = drive(&pool, &cfg, &bus, s, "Dreckige Abholen").await;
    assert_eq!(s3, RequestState::Idle);
    let t = &repo::active_tickets(&pool, Some("BiMi"), None).await.unwrap()[0];
    assert!(t.text.contains("abholen"));
}

#[tokio::test]
async fn bier_freetext_routes_to_bimi() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Bier").await;
    s = s2;
    assert!(matches!(s, RequestState::Free { .. }));
    let (_, s3) = drive(&pool, &cfg, &bus, s, "2 Fässer Pils").await;
    assert_eq!(s3, RequestState::Idle);
    let t = &repo::active_tickets(&pool, Some("BiMi"), None).await.unwrap()[0];
    assert!(t.text.contains("2 Fässer Pils"));
    assert!(t.text.contains("Bier"));
}

#[tokio::test]
async fn sonstiges_routes_to_default_zentrale() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Sonstiges").await;
    s = s2;
    let (_, s3) = drive(&pool, &cfg, &bus, s, "Tape, viel Tape").await;
    assert_eq!(s3, RequestState::Idle);
    let t = &repo::active_tickets(&pool, Some("Zentrale"), None).await.unwrap()[0];
    assert!(t.text.contains("Tape"));
}

#[tokio::test]
async fn helfer_zu_wenige_routes_to_helfen() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Helfer").await;
    s = s2;
    let (_, s3) = drive(&pool, &cfg, &bus, s, "zu wenige").await;
    s = s3;
    assert!(matches!(s, RequestState::Amount { .. }));
    let (_, s4) = drive(&pool, &cfg, &bus, s, "~50").await;
    assert_eq!(s4, RequestState::Idle);
    let t = &repo::active_tickets(&pool, Some("Helfen"), None).await.unwrap()[0];
    assert!(t.text.contains("zu wenige"));
}

#[tokio::test]
async fn helfer_missing_branches_to_free_text() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Helfer").await;
    s = s2;
    let (_, s3) = drive(&pool, &cfg, &bus, s, "Helfer nicht da").await;
    s = s3;
    assert!(matches!(s, RequestState::Free { .. }));
    let (_, s4) = drive(&pool, &cfg, &bus, s, "@bob, @carol").await;
    assert_eq!(s4, RequestState::Idle);
    let t = &repo::active_tickets(&pool, Some("Helfen"), None).await.unwrap()[0];
    assert!(t.text.contains("@bob, @carol"));
}

#[tokio::test]
async fn amount_freetext_branches_to_free_text() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Becher").await;
    s = s2;
    let (_, s3) = drive(&pool, &cfg, &bus, s, "Shotbecher").await;
    s = s3;
    let (_, s4) = drive(&pool, &cfg, &bus, s, "Freitext").await;
    s = s4;
    assert!(matches!(s, RequestState::Free { .. }));
    let (_, s5) = drive(&pool, &cfg, &bus, s, "ca. 250 Stück").await;
    assert_eq!(s5, RequestState::Idle);
    let t = &repo::active_tickets(&pool, Some("BiMi"), None).await.unwrap()[0];
    assert!(t.text.contains("ca. 250"));
}

// --- Side effects on finalize ------------------------------------------

#[tokio::test]
async fn finalize_publishes_to_event_bus() {
    use tokio_stream::StreamExt;

    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;

    let mut sub = Box::pin(bus.subscribe());
    tokio::task::yield_now().await;

    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Geld").await;
    s = s2;
    let _ = drive(&pool, &cfg, &bus, s, "Geld Abholen").await;

    let payload = tokio::time::timeout(std::time::Duration::from_secs(1), sub.next())
        .await
        .expect("timeout")
        .expect("payload");
    assert!(payload.contains("Geld abholen"));
}

#[tokio::test]
async fn finalize_writes_channel_log_and_group_fanout() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let bus = EventBus::new();
    registered_at(&pool, "Cocktailbar 1").await;
    // A second person at the stand who should get the peer notification.
    repo::upsert_registration(&pool, &Registration::new(2, "Cocktailbar 1"))
        .await
        .unwrap();
    // A Finanz member who should get the actionable orga DM.
    repo::upsert_registration(&pool, &Registration::new(7, "Finanz"))
        .await
        .unwrap();

    let mut s = RequestState::Category {
        group: "Cocktailbar 1".into(),
    };
    let (_, s2) = drive(&pool, &cfg, &bus, s, "Geld").await;
    s = s2;
    let (outbox, _) = drive(&pool, &cfg, &bus, s, "Geld Abholen").await;

    // Channel log line was emitted.
    assert!(outbox
        .channel_msgs()
        .iter()
        .any(|m| m.contains("🟠 OPEN")));
    // Stand-peer (chat 2) got a "X in your group created..." DM,
    // Finanz member (chat 7) got the actionable "OPEN #N" DM,
    // the requester themselves (chat 1) is excluded from peer fanout.
    let recipients: Vec<i64> = outbox.dms().iter().map(|(c, _)| **c).collect();
    assert!(recipients.contains(&2));
    assert!(recipients.contains(&7));
    assert!(!recipients.contains(&1));
}
