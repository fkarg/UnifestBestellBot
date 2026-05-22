//! Admin (/closeall) and the unknown-command fallback.

mod common;

use unifestbestellbot::bot::{admin, unknown, Action, Caller, Keyboard, Outbox};
use unifestbestellbot::db::test_pool;
use unifestbestellbot::models::{Registration, TicketStatus};
use unifestbestellbot::repo;

fn dev() -> Caller {
    Caller {
        chat_id: 100,
        username: Some("dev".into()),
        first_name: Some("Dev".into()),
        last_name: None,
    }
}

// --- /closeall ----------------------------------------------------------

#[tokio::test]
async fn closeall_closes_all_open_and_wip_tickets() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let open_t = common::open_ticket(&pool, "still open", "X", "Finanz").await;
    let wip_t = common::open_ticket(&pool, "in progress", "X", "Finanz").await;
    repo::set_wip(&pool, wip_t.id, "alice", 5).await.unwrap();

    let mut outbox = Outbox::new();
    admin::cmd_closeall(&mut outbox, &pool, &cfg, &dev()).await.unwrap();

    assert_eq!(
        repo::get_ticket(&pool, open_t.id)
            .await
            .unwrap()
            .unwrap()
            .status,
        TicketStatus::Closed
    );
    assert_eq!(
        repo::get_ticket(&pool, wip_t.id).await.unwrap().unwrap().status,
        TicketStatus::Closed
    );
}

#[tokio::test]
async fn closeall_reports_count_to_caller() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    common::open_ticket(&pool, "a", "X", "Finanz").await;
    common::open_ticket(&pool, "b", "X", "Finanz").await;
    let mut outbox = Outbox::new();
    admin::cmd_closeall(&mut outbox, &pool, &cfg, &dev()).await.unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains('2'));
}

#[tokio::test]
async fn closeall_empty_state_reports_zero() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    admin::cmd_closeall(&mut outbox, &pool, &cfg, &dev()).await.unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains('0'));
}

#[tokio::test]
async fn closeall_fans_out_to_requesting_and_tasked_groups() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    // Stand member to be notified for their requesting group.
    repo::upsert_registration(&pool, &Registration::new(5, "Cocktailbar 1"))
        .await
        .unwrap();
    // Finanz peer who handled tickets.
    repo::upsert_registration(&pool, &Registration::new(7, "Finanz"))
        .await
        .unwrap();
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;

    let mut outbox = Outbox::new();
    admin::cmd_closeall(&mut outbox, &pool, &cfg, &dev()).await.unwrap();

    let recipients: Vec<i64> = outbox.dms().iter().map(|(c, _)| **c).collect();
    assert!(recipients.contains(&5));
    assert!(recipients.contains(&7));
    let channel = outbox.channel_msgs();
    assert!(channel.iter().any(|m| m.contains(&format!("#{}", t.id))));
}

#[tokio::test]
async fn closeall_attributes_closes_to_entwickler_in_channel_log() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(7, "Finanz"))
        .await
        .unwrap();
    common::open_ticket(&pool, "x", "X", "Finanz").await;
    let mut outbox = Outbox::new();
    admin::cmd_closeall(&mut outbox, &pool, &cfg, &dev()).await.unwrap();
    assert!(outbox.channel_msgs().iter().any(|m| m.contains("Entwickler")));
}

// --- Unknown fallback ---------------------------------------------------

#[tokio::test]
async fn unknown_replies_with_help_hint() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let caller = Caller {
        chat_id: 1,
        username: None,
        first_name: None,
        last_name: None,
    };
    let mut outbox = Outbox::new();
    unknown::cmd_unknown(&mut outbox, &pool, &cfg, &caller).await.unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains("nicht erkannt"));
    assert!(body.contains("/help"));
}

#[tokio::test]
async fn unknown_for_unregistered_uses_initial_keyboard() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let caller = Caller {
        chat_id: 1,
        username: None,
        first_name: None,
        last_name: None,
    };
    let mut outbox = Outbox::new();
    unknown::cmd_unknown(&mut outbox, &pool, &cfg, &caller).await.unwrap();
    if let Action::Reply { keyboard, .. } = &outbox.actions[0] {
        if let Keyboard::Reply(rows) = keyboard {
            let flat: Vec<&str> = rows.iter().flatten().map(String::as_str).collect();
            assert!(flat.contains(&"/register"));
            assert!(!flat.contains(&"/request"));
        }
    }
}

#[tokio::test]
async fn unknown_for_registered_uses_main_keyboard() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let caller = Caller {
        chat_id: 1,
        username: None,
        first_name: None,
        last_name: None,
    };
    let mut outbox = Outbox::new();
    unknown::cmd_unknown(&mut outbox, &pool, &cfg, &caller).await.unwrap();
    if let Action::Reply { keyboard, .. } = &outbox.actions[0] {
        if let Keyboard::Reply(rows) = keyboard {
            let flat: Vec<&str> = rows.iter().flatten().map(String::as_str).collect();
            assert!(flat.contains(&"/request"));
        }
    }
}
