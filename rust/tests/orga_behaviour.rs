//! Behavioural tests for the orga commands. Drive the handlers,
//! assert on the outbox + the DB.

mod common;

use unifestbestellbot::bot::{orga as flow, Action, Caller, Keyboard, Outbox};
use unifestbestellbot::db::test_pool;
use unifestbestellbot::models::{Registration, TicketStatus};
use unifestbestellbot::repo;

fn orga_alice() -> Caller {
    Caller {
        chat_id: 1,
        username: Some("alice".into()),
        first_name: Some("Alice".into()),
        last_name: None,
    }
}

async fn registered(pool: &sqlx::SqlitePool, chat_id: i64, group: &str) {
    repo::upsert_registration(pool, &Registration::new(chat_id, group))
        .await
        .unwrap();
}

async fn finanz_orga(pool: &sqlx::SqlitePool) {
    registered(pool, 1, "Finanz").await;
}

// --- IsOrga gate --------------------------------------------------------

#[tokio::test]
async fn orga_guard_rejects_unregistered_user() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_tickets(&mut outbox, &pool, &cfg, &orga_alice())
        .await
        .unwrap();
    assert!(outbox.reply_texts()[0].contains("nicht erlaubt"));
}

#[tokio::test]
async fn orga_guard_rejects_stand_member() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    registered(&pool, 1, "Cocktailbar 1").await;
    let mut outbox = Outbox::new();
    flow::cmd_tickets(&mut outbox, &pool, &cfg, &orga_alice())
        .await
        .unwrap();
    assert!(outbox.reply_texts()[0].contains("nicht erlaubt"));
}

#[tokio::test]
async fn orga_guard_accepts_orga_member() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let mut outbox = Outbox::new();
    flow::cmd_tickets(&mut outbox, &pool, &cfg, &orga_alice())
        .await
        .unwrap();
    // Empty state still shows the German "no open tickets" text, not the
    // permission denial.
    assert!(!outbox.reply_texts()[0].contains("nicht erlaubt"));
}

// --- /tickets, /all -----------------------------------------------------

#[tokio::test]
async fn tickets_empty_for_orga_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let mut outbox = Outbox::new();
    flow::cmd_tickets(&mut outbox, &pool, &cfg, &orga_alice())
        .await
        .unwrap();
    assert!(outbox.reply_texts()[0].contains("keine offenen Tickets"));
}

#[tokio::test]
async fn tickets_lists_own_group_only() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    common::open_ticket(&pool, "finanz one", "X", "Finanz").await;
    common::open_ticket(&pool, "bimi one", "X", "BiMi").await;
    let mut outbox = Outbox::new();
    flow::cmd_tickets(&mut outbox, &pool, &cfg, &orga_alice())
        .await
        .unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains("finanz one"));
    assert!(!body.contains("bimi one"));
}

#[tokio::test]
async fn all_groups_orga_groups_in_output() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    common::open_ticket(&pool, "finanz one", "X", "Finanz").await;
    common::open_ticket(&pool, "bimi one", "X", "BiMi").await;
    let mut outbox = Outbox::new();
    flow::cmd_all(&mut outbox, &pool, &cfg, &orga_alice()).await.unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains("[Finanz]"));
    assert!(body.contains("[BiMi]"));
    assert!(body.contains("finanz one"));
    assert!(body.contains("bimi one"));
}

#[tokio::test]
async fn all_when_empty() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let mut outbox = Outbox::new();
    flow::cmd_all(&mut outbox, &pool, &cfg, &orga_alice()).await.unwrap();
    assert!(outbox.reply_texts()[0].contains("keine offenen Tickets"));
}

// --- /wip ---------------------------------------------------------------

#[tokio::test]
async fn wip_with_explicit_id_marks_ticket_wip() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_wip(&mut outbox, &pool, &cfg, &orga_alice(), Some(&t.id.to_string()))
        .await
        .unwrap();
    assert_eq!(
        repo::get_ticket(&pool, t.id).await.unwrap().unwrap().status,
        TicketStatus::Wip
    );
}

#[tokio::test]
async fn wip_without_id_shows_picker_with_open_tickets() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_wip(&mut outbox, &pool, &cfg, &orga_alice(), None).await.unwrap();
    let Action::Reply {
        keyboard: Keyboard::Inline(buttons),
        ..
    } = &outbox.actions[0]
    else {
        panic!("expected inline picker");
    };
    let cbs: Vec<&str> = buttons.iter().map(|(_, c)| c.as_str()).collect();
    assert!(cbs.contains(&format!("wip:{}", t.id).as_str()));
    assert!(cbs.contains(&"wip:_cancel"));
}

#[tokio::test]
async fn wip_picker_empty_when_no_open_tickets() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::set_wip(&pool, t.id, "x", 1).await.unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_wip(&mut outbox, &pool, &cfg, &orga_alice(), None).await.unwrap();
    assert!(outbox.reply_texts()[0].contains("Keine offenen Tickets"));
}

#[tokio::test]
async fn wip_callback_transitions_to_wip() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::on_wip_choice(&mut outbox, &pool, &cfg, &orga_alice(), &t.id.to_string())
        .await
        .unwrap();
    assert_eq!(
        repo::get_ticket(&pool, t.id).await.unwrap().unwrap().status,
        TicketStatus::Wip
    );
    assert!(
        outbox
            .actions
            .iter()
            .any(|a| matches!(a, Action::AnswerCallback { .. }))
    );
}

#[tokio::test]
async fn wip_callback_cancel_does_nothing() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::on_wip_choice(&mut outbox, &pool, &cfg, &orga_alice(), "_cancel")
        .await
        .unwrap();
    assert_eq!(
        repo::get_ticket(&pool, t.id).await.unwrap().unwrap().status,
        TicketStatus::Open
    );
}

#[tokio::test]
async fn wip_rejects_already_wip_ticket() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::set_wip(&pool, t.id, "someone", 99).await.unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_wip(&mut outbox, &pool, &cfg, &orga_alice(), Some(&t.id.to_string()))
        .await
        .unwrap();
    assert!(outbox.reply_texts()[0].contains("arbeitet bereits"));
}

#[tokio::test]
async fn wip_missing_ticket_reports_so() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let mut outbox = Outbox::new();
    flow::cmd_wip(&mut outbox, &pool, &cfg, &orga_alice(), Some("999"))
        .await
        .unwrap();
    assert!(outbox.reply_texts()[0].contains("geschlossen oder existiert noch nicht"));
}

// --- /close --------------------------------------------------------------

#[tokio::test]
async fn close_with_id_closes() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::set_wip(&pool, t.id, "x", 1).await.unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_close(&mut outbox, &pool, &cfg, &orga_alice(), Some(&t.id.to_string()))
        .await
        .unwrap();
    assert_eq!(
        repo::get_ticket(&pool, t.id).await.unwrap().unwrap().status,
        TicketStatus::Closed
    );
}

#[tokio::test]
async fn close_can_skip_wip() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_close(&mut outbox, &pool, &cfg, &orga_alice(), Some(&t.id.to_string()))
        .await
        .unwrap();
    assert_eq!(
        repo::get_ticket(&pool, t.id).await.unwrap().unwrap().status,
        TicketStatus::Closed
    );
}

#[tokio::test]
async fn close_picker_only_lists_wip_tickets() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let open_t = common::open_ticket(&pool, "still open", "X", "Finanz").await;
    let wip_t = common::open_ticket(&pool, "being worked", "X", "Finanz").await;
    repo::set_wip(&pool, wip_t.id, "x", 1).await.unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_close(&mut outbox, &pool, &cfg, &orga_alice(), None).await.unwrap();
    let Action::Reply {
        keyboard: Keyboard::Inline(buttons),
        ..
    } = &outbox.actions[0]
    else {
        panic!("expected picker");
    };
    let cbs: Vec<&str> = buttons.iter().map(|(_, c)| c.as_str()).collect();
    assert!(cbs.contains(&format!("close:{}", wip_t.id).as_str()));
    assert!(!cbs.contains(&format!("close:{}", open_t.id).as_str()));
}

// --- /move --------------------------------------------------------------

#[tokio::test]
async fn move_changes_group_tasked() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_move(
        &mut outbox,
        &pool,
        &cfg,
        &orga_alice(),
        Some(&format!("{} BiMi", t.id)),
    )
    .await
    .unwrap();
    assert_eq!(
        repo::get_ticket(&pool, t.id)
            .await
            .unwrap()
            .unwrap()
            .group_tasked,
        "BiMi"
    );
}

#[tokio::test]
async fn move_rejects_wip_tickets_without_false_success() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    repo::set_wip(&pool, t.id, "x", 1).await.unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_move(
        &mut outbox,
        &pool,
        &cfg,
        &orga_alice(),
        Some(&format!("{} BiMi", t.id)),
    )
    .await
    .unwrap();
    assert!(outbox.reply_texts()[0].contains("bereits bearbeitet"));
    // No bogus channel "MOVED" line.
    assert!(outbox.channel_msgs().iter().all(|m| !m.contains("MOVED")));
    assert_eq!(
        repo::get_ticket(&pool, t.id)
            .await
            .unwrap()
            .unwrap()
            .group_tasked,
        "Finanz"
    );
}

#[tokio::test]
async fn move_rejects_unknown_target_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "X", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_move(
        &mut outbox,
        &pool,
        &cfg,
        &orga_alice(),
        Some(&format!("{} NoSuchGroup", t.id)),
    )
    .await
    .unwrap();
    assert_eq!(
        repo::get_ticket(&pool, t.id)
            .await
            .unwrap()
            .unwrap()
            .group_tasked,
        "Finanz"
    );
}

#[tokio::test]
async fn move_missing_args_shows_usage() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let mut outbox = Outbox::new();
    flow::cmd_move(&mut outbox, &pool, &cfg, &orga_alice(), None).await.unwrap();
    assert!(outbox.reply_texts()[0].contains("Benutzung"));
}

#[tokio::test]
async fn move_notifies_target_orga_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    // BiMi member who should receive the move-notification.
    registered(&pool, 7, "BiMi").await;
    let t = common::open_ticket(&pool, "needs cocktail", "X", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_move(
        &mut outbox,
        &pool,
        &cfg,
        &orga_alice(),
        Some(&format!("{} BiMi", t.id)),
    )
    .await
    .unwrap();
    let recipients: Vec<i64> = outbox.dms().iter().map(|(c, _)| **c).collect();
    assert!(recipients.contains(&7));
}

// --- /message ------------------------------------------------------------

#[tokio::test]
async fn message_forwards_to_requesting_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    registered(&pool, 2, "Cocktailbar 1").await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_message(
        &mut outbox,
        &pool,
        &cfg,
        &orga_alice(),
        Some(&format!("{} Hallo welt", t.id)),
    )
    .await
    .unwrap();
    let dms = outbox.dms();
    assert!(dms.iter().any(|(c, t)| **c == 2 && t.contains("Hallo welt")));
}

#[tokio::test]
async fn message_records_audit_event() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "x", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_message(
        &mut outbox,
        &pool,
        &cfg,
        &orga_alice(),
        Some(&format!("{} Heads up", t.id)),
    )
    .await
    .unwrap();
    let audit = repo::all_audit(&pool).await.unwrap();
    assert!(audit.iter().any(|e| e.kind == "message"
        && e.payload_json
            .as_deref()
            .map(|p| p.contains("Heads up"))
            .unwrap_or(false)));
}

#[tokio::test]
async fn message_missing_args_shows_usage() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let mut outbox = Outbox::new();
    flow::cmd_message(&mut outbox, &pool, &cfg, &orga_alice(), None)
        .await
        .unwrap();
    assert!(outbox.reply_texts()[0].contains("Benutzung"));
}

// --- /bug, /feature -----------------------------------------------------

#[tokio::test]
async fn bug_forwards_to_developer() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_bug(
        &mut outbox,
        &pool,
        &cfg,
        &orga_alice(),
        Some("things are broken"),
    )
    .await
    .unwrap();
    assert!(outbox
        .actions
        .iter()
        .any(|a| matches!(a, Action::Dev(t) if t.contains("things are broken"))));
}

#[tokio::test]
async fn bug_without_args_shows_usage() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_bug(&mut outbox, &pool, &cfg, &orga_alice(), None).await.unwrap();
    assert!(outbox.reply_texts()[0].contains("Benutzung"));
}

#[tokio::test]
async fn feature_forwards_to_developer() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_feature(
        &mut outbox,
        &pool,
        &cfg,
        &orga_alice(),
        Some("better dashboard"),
    )
    .await
    .unwrap();
    assert!(outbox
        .actions
        .iter()
        .any(|a| matches!(a, Action::Dev(t) if t.contains("better dashboard"))));
}

// --- /history ------------------------------------------------------------

#[tokio::test]
async fn history_shows_recent_closes_for_orga_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let t = common::open_ticket(&pool, "bezahlt", "Cocktailbar 1", "Finanz").await;
    repo::close_ticket(&pool, t.id, 1).await.unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_history(&mut outbox, &pool, &cfg, &orga_alice(), None)
        .await
        .unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains("bezahlt"));
    assert!(body.contains("Finanz")); // header names the group
}

#[tokio::test]
async fn history_explicit_n_limits_results() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    for i in 0..5 {
        let t = common::open_ticket(&pool, &format!("t{}", i), "X", "Finanz").await;
        repo::close_ticket(&pool, t.id, 1).await.unwrap();
    }
    let mut outbox = Outbox::new();
    flow::cmd_history(&mut outbox, &pool, &cfg, &orga_alice(), Some("2"))
        .await
        .unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains("t4"));
    assert!(body.contains("t3"));
    assert!(!body.contains("t0"));
    assert!(!body.contains("t1"));
}

#[tokio::test]
async fn history_empty_state() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let mut outbox = Outbox::new();
    flow::cmd_history(&mut outbox, &pool, &cfg, &orga_alice(), None)
        .await
        .unwrap();
    assert!(outbox.reply_texts()[0].contains("Keine geschlossenen"));
}

#[tokio::test]
async fn history_rejects_out_of_range_and_garbage() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    for bad in ["0", "9999", "abc"] {
        let mut outbox = Outbox::new();
        flow::cmd_history(&mut outbox, &pool, &cfg, &orga_alice(), Some(bad))
            .await
            .unwrap();
        assert!(
            outbox.reply_texts()[0].contains("Benutzung"),
            "should reject {bad:?}"
        );
    }
}

#[tokio::test]
async fn history_scopes_to_callers_orga_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    finanz_orga(&pool).await;
    let f = common::open_ticket(&pool, "finanz one", "X", "Finanz").await;
    repo::close_ticket(&pool, f.id, 1).await.unwrap();
    let b = common::open_ticket(&pool, "bimi one", "X", "BiMi").await;
    repo::close_ticket(&pool, b.id, 1).await.unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_history(&mut outbox, &pool, &cfg, &orga_alice(), None)
        .await
        .unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains("finanz one"));
    assert!(!body.contains("bimi one"));
}
