//! Behavioural tests for the repo: ticket lifecycle, registration,
//! mute, audit, history. End-to-end against an in-memory SQLite —
//! every test sees the same SQL the production code does.

mod common;

use chrono::Duration;
use unifestbestellbot::db::test_pool;
use unifestbestellbot::models::{now_utc, Registration, TicketStatus};
use unifestbestellbot::repo;

// --- Registration --------------------------------------------------------

#[tokio::test]
async fn upsert_inserts_new_registration() {
    let pool = test_pool().await;
    let reg = Registration {
        chat_id: 1,
        group_name: "Cocktailbar 1".into(),
        username: Some("alice".into()),
        first_name: Some("Alice".into()),
        last_name: None,
        registered_at: now_utc(),
        mute_peer_until: None,
    };
    let stored = repo::upsert_registration(&pool, &reg).await.unwrap();
    assert_eq!(stored.chat_id, 1);
    assert_eq!(stored.group_name, "Cocktailbar 1");
    assert_eq!(stored.username.as_deref(), Some("alice"));
}

#[tokio::test]
async fn upsert_overwrites_previous_group() {
    let pool = test_pool().await;
    let mut reg = Registration::new(1, "Cocktailbar 1");
    repo::upsert_registration(&pool, &reg).await.unwrap();
    reg.group_name = "Biertheke 1".into();
    repo::upsert_registration(&pool, &reg).await.unwrap();
    let current = repo::registration_for(&pool, 1).await.unwrap().unwrap();
    assert_eq!(current.group_name, "Biertheke 1");
}

#[tokio::test]
async fn unregister_returns_previous_group_and_removes_row() {
    let pool = test_pool().await;
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let prev = repo::unregister(&pool, 1).await.unwrap();
    assert_eq!(prev.as_deref(), Some("Cocktailbar 1"));
    assert!(repo::registration_for(&pool, 1).await.unwrap().is_none());
}

#[tokio::test]
async fn unregister_when_not_registered_returns_none() {
    let pool = test_pool().await;
    assert!(repo::unregister(&pool, 99).await.unwrap().is_none());
}

#[tokio::test]
async fn group_members_lists_all_chat_ids() {
    let pool = test_pool().await;
    repo::upsert_registration(&pool, &Registration::new(1, "BiMi")).await.unwrap();
    repo::upsert_registration(&pool, &Registration::new(2, "BiMi")).await.unwrap();
    repo::upsert_registration(&pool, &Registration::new(3, "Finanz")).await.unwrap();
    let mut bimi = repo::group_members(&pool, "BiMi", false).await.unwrap();
    bimi.sort();
    assert_eq!(bimi, vec![1, 2]);
    assert_eq!(repo::group_members(&pool, "Finanz", false).await.unwrap(), vec![3]);
}

// --- Mute / quiet --------------------------------------------------------

#[tokio::test]
async fn group_members_excludes_muted_when_requested() {
    let pool = test_pool().await;
    for chat_id in [1, 2, 3] {
        repo::upsert_registration(&pool, &Registration::new(chat_id, "BiMi"))
            .await
            .unwrap();
    }
    repo::set_mute(&pool, 2, Some(now_utc() + Duration::minutes(30)))
        .await
        .unwrap();

    let mut peer_mode = repo::group_members(&pool, "BiMi", true).await.unwrap();
    peer_mode.sort();
    assert_eq!(peer_mode, vec![1, 3]);

    let mut broadcast = repo::group_members(&pool, "BiMi", false).await.unwrap();
    broadcast.sort();
    assert_eq!(broadcast, vec![1, 2, 3]);
}

#[tokio::test]
async fn expired_mute_is_treated_as_unmuted() {
    let pool = test_pool().await;
    repo::upsert_registration(&pool, &Registration::new(1, "BiMi"))
        .await
        .unwrap();
    repo::set_mute(&pool, 1, Some(now_utc() - Duration::minutes(1)))
        .await
        .unwrap();
    assert_eq!(repo::group_members(&pool, "BiMi", true).await.unwrap(), vec![1]);
}

// --- Tickets -------------------------------------------------------------

#[tokio::test]
async fn create_sets_open_status_and_id() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    assert!(t.id > 0);
    assert_eq!(t.status, TicketStatus::Open);
    assert!(t.closed_at.is_none());
}

#[tokio::test]
async fn wip_transitions_status_and_records_who() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let after = repo::set_wip(&pool, t.id, "Alice", 99).await.unwrap();
    assert_eq!(after.status, TicketStatus::Wip);
    assert_eq!(after.who_wip.as_deref(), Some("Alice"));
}

#[tokio::test]
async fn wip_rejects_non_open_ticket() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::set_wip(&pool, t.id, "Alice", 99).await.unwrap();
    let err = repo::set_wip(&pool, t.id, "Bob", 99).await.unwrap_err();
    assert!(matches!(err, repo::RepoError::InvalidTransition(_)));
}

#[tokio::test]
async fn close_marks_closed_and_sets_timestamp() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::set_wip(&pool, t.id, "Alice", 99).await.unwrap();
    let closed = repo::close_ticket(&pool, t.id, 99).await.unwrap();
    assert_eq!(closed.status, TicketStatus::Closed);
    assert!(closed.closed_at.is_some());
}

#[tokio::test]
async fn close_can_skip_wip() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let closed = repo::close_ticket(&pool, t.id, 99).await.unwrap();
    assert_eq!(closed.status, TicketStatus::Closed);
}

#[tokio::test]
async fn close_rejects_already_closed_ticket() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::close_ticket(&pool, t.id, 99).await.unwrap();
    let err = repo::close_ticket(&pool, t.id, 99).await.unwrap_err();
    assert!(matches!(err, repo::RepoError::InvalidTransition(_)));
}

#[tokio::test]
async fn move_changes_group_tasked_on_open_ticket() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let moved = repo::move_ticket(&pool, t.id, "BiMi", 1).await.unwrap();
    assert_eq!(moved.group_tasked, "BiMi");
}

#[tokio::test]
async fn move_rejects_wip_ticket() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::set_wip(&pool, t.id, "Alice", 1).await.unwrap();
    let err = repo::move_ticket(&pool, t.id, "BiMi", 1).await.unwrap_err();
    assert!(matches!(err, repo::RepoError::InvalidTransition(_)));
}

#[tokio::test]
async fn active_tickets_excludes_closed() {
    let pool = test_pool().await;
    let a = common::open_ticket(&pool, "a", "Cocktailbar 1", "Finanz").await;
    let b = common::open_ticket(&pool, "b", "Cocktailbar 1", "Finanz").await;
    repo::close_ticket(&pool, b.id, 1).await.unwrap();
    let active = repo::active_tickets(&pool, None, None).await.unwrap();
    let ids: Vec<i64> = active.iter().map(|t| t.id).collect();
    assert!(ids.contains(&a.id));
    assert!(!ids.contains(&b.id));
}

#[tokio::test]
async fn active_tickets_filters_by_tasked_group() {
    let pool = test_pool().await;
    common::open_ticket(&pool, "finanz one", "X", "Finanz").await;
    let bimi = common::open_ticket(&pool, "bimi one", "X", "BiMi").await;
    let only_bimi = repo::active_tickets(&pool, Some("BiMi"), None).await.unwrap();
    assert_eq!(only_bimi.len(), 1);
    assert_eq!(only_bimi[0].id, bimi.id);
}

#[tokio::test]
async fn active_tickets_filters_by_status() {
    let pool = test_pool().await;
    let a = common::open_ticket(&pool, "open", "X", "Finanz").await;
    let b = common::open_ticket(&pool, "wip", "X", "Finanz").await;
    repo::set_wip(&pool, b.id, "Alice", 1).await.unwrap();

    let opens = repo::active_tickets(&pool, None, Some(TicketStatus::Open))
        .await
        .unwrap();
    assert_eq!(opens.iter().map(|t| t.id).collect::<Vec<_>>(), vec![a.id]);

    let wips = repo::active_tickets(&pool, None, Some(TicketStatus::Wip))
        .await
        .unwrap();
    assert_eq!(wips.iter().map(|t| t.id).collect::<Vec<_>>(), vec![b.id]);
}

#[tokio::test]
async fn tickets_requested_by_excludes_closed() {
    let pool = test_pool().await;
    let a = common::open_ticket(&pool, "a", "Cocktailbar 1", "Finanz").await;
    let b = common::open_ticket(&pool, "b", "Cocktailbar 1", "Finanz").await;
    repo::close_ticket(&pool, b.id, 1).await.unwrap();
    let open_for = repo::tickets_requested_by(&pool, "Cocktailbar 1")
        .await
        .unwrap();
    assert_eq!(open_for.iter().map(|t| t.id).collect::<Vec<_>>(), vec![a.id]);
}

// --- Audit log -----------------------------------------------------------

#[tokio::test]
async fn audit_records_full_ticket_lifecycle() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::set_wip(&pool, t.id, "Alice", 99).await.unwrap();
    repo::close_ticket(&pool, t.id, 99).await.unwrap();
    let kinds: Vec<String> = repo::all_audit(&pool)
        .await
        .unwrap()
        .into_iter()
        .map(|e| e.kind)
        .collect();
    assert_eq!(kinds, vec!["open", "wip", "close"]);
}

#[tokio::test]
async fn audit_records_register_and_unregister() {
    let pool = test_pool().await;
    repo::upsert_registration(&pool, &Registration::new(1, "X"))
        .await
        .unwrap();
    repo::unregister(&pool, 1).await.unwrap();
    let kinds: Vec<String> = repo::all_audit(&pool)
        .await
        .unwrap()
        .into_iter()
        .map(|e| e.kind)
        .collect();
    assert_eq!(kinds, vec!["register", "unregister"]);
}

#[tokio::test]
async fn audit_records_move_with_payload() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::move_ticket(&pool, t.id, "BiMi", 1).await.unwrap();
    let events = repo::all_audit(&pool).await.unwrap();
    let move_event = events.iter().find(|e| e.kind == "move").unwrap();
    let payload = move_event.payload_json.as_deref().unwrap();
    assert!(payload.contains("BiMi"));
    assert!(payload.contains("Finanz"));
}

#[tokio::test]
async fn record_message_writes_audit_row() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::record_message(&pool, t.id, 5, "hello").await.unwrap();
    let msgs: Vec<_> = repo::all_audit(&pool)
        .await
        .unwrap()
        .into_iter()
        .filter(|e| e.kind == "message")
        .collect();
    assert_eq!(msgs.len(), 1);
    assert!(msgs[0].payload_json.as_deref().unwrap().contains("hello"));
}

// --- Recent closes / history --------------------------------------------

#[tokio::test]
async fn recent_closes_empty_when_nothing_closed() {
    let pool = test_pool().await;
    let summaries = repo::recent_closes(&pool, None, 10).await.unwrap();
    assert!(summaries.is_empty());
}

#[tokio::test]
async fn recent_closes_returns_newest_first() {
    let pool = test_pool().await;
    for text in ["first", "second", "third"] {
        let t = common::open_ticket(&pool, text, "Cocktailbar 1", "Finanz").await;
        repo::close_ticket(&pool, t.id, 1).await.unwrap();
    }
    let summaries = repo::recent_closes(&pool, None, 10).await.unwrap();
    let texts: Vec<String> = summaries.iter().map(|s| s.ticket.text.clone()).collect();
    assert_eq!(texts, vec!["third", "second", "first"]);
}

#[tokio::test]
async fn recent_closes_filters_by_group_tasked() {
    let pool = test_pool().await;
    let a = common::open_ticket(&pool, "finanz one", "X", "Finanz").await;
    repo::close_ticket(&pool, a.id, 1).await.unwrap();
    let b = common::open_ticket(&pool, "bimi one", "X", "BiMi").await;
    repo::close_ticket(&pool, b.id, 1).await.unwrap();

    let only_finanz = repo::recent_closes(&pool, Some("Finanz"), 10).await.unwrap();
    let texts: Vec<String> = only_finanz.iter().map(|s| s.ticket.text.clone()).collect();
    assert_eq!(texts, vec!["finanz one"]);
}

#[tokio::test]
async fn recent_closes_resolves_registered_closer_to_display_name() {
    let pool = test_pool().await;
    repo::upsert_registration(
        &pool,
        &Registration {
            chat_id: 42,
            group_name: "Finanz".into(),
            username: Some("alice".into()),
            first_name: Some("Alice".into()),
            last_name: None,
            registered_at: now_utc(),
            mute_peer_until: None,
        },
    )
    .await
    .unwrap();
    let t = common::open_ticket(&pool, "x", "X", "Finanz").await;
    repo::close_ticket(&pool, t.id, 42).await.unwrap();
    let summaries = repo::recent_closes(&pool, None, 10).await.unwrap();
    assert!(summaries[0].closer_display.contains("Alice"));
    assert!(summaries[0].closer_display.contains("alice"));
}

#[tokio::test]
async fn recent_closes_falls_back_to_chat_id_for_unregistered_closer() {
    let pool = test_pool().await;
    let t = common::open_ticket(&pool, "x", "X", "Finanz").await;
    repo::close_ticket(&pool, t.id, 9999).await.unwrap();
    let summaries = repo::recent_closes(&pool, None, 10).await.unwrap();
    assert!(summaries[0].closer_display.contains("9999"));
}
