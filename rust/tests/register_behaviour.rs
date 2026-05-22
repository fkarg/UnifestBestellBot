//! Behavioural tests for the registration commands. Drive the handler
//! logic functions directly; assert on the outbox + the DB.

mod common;

use unifestbestellbot::bot::{register as flow, Caller, Keyboard, Outbox};
use unifestbestellbot::db::test_pool;
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

// --- /start --------------------------------------------------------------

#[tokio::test]
async fn start_for_unregistered_user_offers_initial_keyboard() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_start(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    let reply = outbox.actions.first().unwrap();
    match reply {
        unifestbestellbot::bot::Action::Reply { text, keyboard } => {
            assert!(text.contains("UnifestBestellBot"));
            // Initial keyboard: /register is offered, /request isn't.
            if let Keyboard::Reply(rows) = keyboard {
                let flat: Vec<&str> = rows.iter().flatten().map(String::as_str).collect();
                assert!(flat.contains(&"/register"));
                assert!(!flat.contains(&"/request"));
            } else {
                panic!("expected reply keyboard, got {:?}", keyboard);
            }
        }
        _ => panic!("expected Reply"),
    }
}

#[tokio::test]
async fn start_for_registered_stand_offers_main_keyboard() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_start(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    if let unifestbestellbot::bot::Action::Reply { keyboard, .. } = &outbox.actions[0] {
        if let Keyboard::Reply(rows) = keyboard {
            let flat: Vec<&str> = rows.iter().flatten().map(String::as_str).collect();
            assert!(flat.contains(&"/request"));
        }
    }
}

#[tokio::test]
async fn start_for_orga_member_offers_orga_keyboard() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Finanz"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_start(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    if let unifestbestellbot::bot::Action::Reply { keyboard, .. } = &outbox.actions[0] {
        if let Keyboard::Reply(rows) = keyboard {
            let flat: Vec<&str> = rows.iter().flatten().map(String::as_str).collect();
            assert!(flat.contains(&"/help2"));
            assert!(flat.contains(&"/wip"));
        }
    }
}

// --- /help ---------------------------------------------------------------

#[tokio::test]
async fn help_for_stand_member_omits_orga_commands() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_help(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    let text = outbox.reply_texts().join("\n");
    assert!(text.contains("/request"));
    assert!(!text.contains("/move"));
}

#[tokio::test]
async fn help_for_orga_member_returns_orga_help() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Finanz"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_help(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    let text = outbox.reply_texts().join("\n");
    assert!(text.contains("/move"));
    assert!(text.contains("/wip"));
}

// --- /register picker contents ------------------------------------------

#[tokio::test]
async fn register_picker_shows_only_visible_stalls() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_register(&mut outbox, &pool, &cfg, &alice(), None)
        .await
        .unwrap();
    match &outbox.actions[0] {
        unifestbestellbot::bot::Action::Reply {
            keyboard: Keyboard::Inline(buttons),
            ..
        } => {
            let labels: Vec<&str> = buttons.iter().map(|(l, _)| l.as_str()).collect();
            assert!(labels.contains(&"Cocktailbar 1"));
            assert!(labels.contains(&"Biertheke 1"));
            // Orga groups are intentionally absent.
            assert!(!labels.contains(&"Finanz"));
            assert!(!labels.contains(&"BiMi"));
            // Hidden stalls are absent.
            assert!(!labels.contains(&"Tickets"));
            assert!(labels.iter().any(|l| l.contains("Abbrechen")));
        }
        a => panic!("expected inline keyboard, got {:?}", a),
    }
}

// --- /register textual arg ----------------------------------------------

#[tokio::test]
async fn register_textual_arg_registers_orga_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_register(&mut outbox, &pool, &cfg, &alice(), Some("Finanz"))
        .await
        .unwrap();
    let saved = repo::registration_for(&pool, 1).await.unwrap().unwrap();
    assert_eq!(saved.group_name, "Finanz");
    assert!(outbox
        .channel_msgs()
        .iter()
        .any(|m| m.contains("registered") && m.contains("Finanz")));
}

#[tokio::test]
async fn register_textual_arg_registers_hidden_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_register(&mut outbox, &pool, &cfg, &alice(), Some("Tickets"))
        .await
        .unwrap();
    let saved = repo::registration_for(&pool, 1).await.unwrap().unwrap();
    assert_eq!(saved.group_name, "Tickets");
}

#[tokio::test]
async fn register_textual_arg_is_case_insensitive() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_register(&mut outbox, &pool, &cfg, &alice(), Some("finanz"))
        .await
        .unwrap();
    let saved = repo::registration_for(&pool, 1).await.unwrap().unwrap();
    assert_eq!(saved.group_name, "Finanz"); // canonical casing preserved
}

#[tokio::test]
async fn register_textual_arg_unknown_group_is_rejected() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_register(&mut outbox, &pool, &cfg, &alice(), Some("HackerGroup"))
        .await
        .unwrap();
    assert!(repo::registration_for(&pool, 1).await.unwrap().is_none());
    assert!(outbox.reply_texts()[0].contains("Unbekannte"));
}

// --- /register inline-callback path -------------------------------------

#[tokio::test]
async fn register_callback_persists_visible_stall() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::on_register_choice(&mut outbox, &pool, &cfg, &alice(), "Cocktailbar 1")
        .await
        .unwrap();
    let saved = repo::registration_for(&pool, 1).await.unwrap().unwrap();
    assert_eq!(saved.group_name, "Cocktailbar 1");

    // Saw an edit (success text), a DM to the user (keyboard update),
    // a channel post (registration log), and an answered callback.
    let mut saw_edit = false;
    let mut saw_dm = false;
    let mut saw_channel = false;
    let mut saw_answer = false;
    for action in &outbox.actions {
        use unifestbestellbot::bot::Action::*;
        match action {
            EditMessage(t) if t.contains("Cocktailbar 1") => saw_edit = true,
            Dm { text, .. } if text == "Tastatur aktualisiert." => saw_dm = true,
            Channel(t) if t.contains("Cocktailbar 1") => saw_channel = true,
            AnswerCallback { .. } => saw_answer = true,
            _ => {}
        }
    }
    assert!(saw_edit && saw_dm && saw_channel && saw_answer);
}

#[tokio::test]
async fn register_callback_rejects_orga_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::on_register_choice(&mut outbox, &pool, &cfg, &alice(), "Finanz")
        .await
        .unwrap();
    assert!(repo::registration_for(&pool, 1).await.unwrap().is_none());
    let answered = outbox
        .actions
        .iter()
        .find(|a| matches!(a, unifestbestellbot::bot::Action::AnswerCallback { alert: true, .. }));
    assert!(answered.is_some());
}

#[tokio::test]
async fn register_callback_rejects_hidden_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::on_register_choice(&mut outbox, &pool, &cfg, &alice(), "Tickets")
        .await
        .unwrap();
    assert!(repo::registration_for(&pool, 1).await.unwrap().is_none());
}

#[tokio::test]
async fn register_callback_cancel_does_not_persist() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::on_register_choice(&mut outbox, &pool, &cfg, &alice(), "_cancel")
        .await
        .unwrap();
    assert!(repo::registration_for(&pool, 1).await.unwrap().is_none());
    assert!(outbox
        .actions
        .iter()
        .any(|a| matches!(a, unifestbestellbot::bot::Action::EditMessage(t) if t.contains("abgebrochen"))));
}

// --- /unregister ---------------------------------------------------------

#[tokio::test]
async fn unregister_removes_registration() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_unregister(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    assert!(repo::registration_for(&pool, 1).await.unwrap().is_none());
    let text = outbox.reply_texts()[0];
    assert!(text.contains("Cocktailbar 1"));
}

#[tokio::test]
async fn unregister_when_not_registered_is_safe() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_unregister(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    assert!(outbox.reply_texts()[0].contains("Nichts zu entfernen"));
}

// --- /status -------------------------------------------------------------

#[tokio::test]
async fn status_without_registration_says_so() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_status(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    assert!(outbox.reply_texts()[0].contains("Keine Gruppenmitgliedschaft"));
}

#[tokio::test]
async fn status_no_open_tickets_for_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_status(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains("Cocktailbar 1"));
    assert!(body.contains("keine offenen Tickets"));
}

#[tokio::test]
async fn status_lists_open_tickets_for_requesting_group() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    common::open_ticket(&pool, "Wechselgeld Münzen", "Cocktailbar 1", "Finanz").await;
    let mut outbox = Outbox::new();
    flow::cmd_status(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    let body = outbox.reply_texts()[0];
    assert!(body.contains("Wechselgeld Münzen"));
    assert!(body.contains("1 Ticket"));
}

// --- /quiet / /loud ------------------------------------------------------

#[tokio::test]
async fn quiet_default_30_minutes() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_quiet(&mut outbox, &pool, &cfg, &alice(), None).await.unwrap();
    let saved = repo::registration_for(&pool, 1).await.unwrap().unwrap();
    assert!(saved.mute_peer_until.is_some());
    assert!(outbox.reply_texts()[0].contains("30"));
}

#[tokio::test]
async fn quiet_custom_minutes() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_quiet(&mut outbox, &pool, &cfg, &alice(), Some("120"))
        .await
        .unwrap();
    let saved = repo::registration_for(&pool, 1).await.unwrap().unwrap();
    let delta = saved.mute_peer_until.unwrap() - unifestbestellbot::models::now_utc();
    assert!(delta.num_minutes() > 118 && delta.num_minutes() < 121);
}

#[tokio::test]
async fn quiet_rejects_zero_negative_huge_and_garbage() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    for bad in ["0", "-5", "9999", "abc"] {
        let mut outbox = Outbox::new();
        flow::cmd_quiet(&mut outbox, &pool, &cfg, &alice(), Some(bad))
            .await
            .unwrap();
        let saved = repo::registration_for(&pool, 1).await.unwrap().unwrap();
        assert!(
            saved.mute_peer_until.is_none(),
            "should reject quiet arg {:?}",
            bad
        );
        assert!(
            outbox.reply_texts()[0].contains("Benutzung"),
            "should explain usage for {:?}",
            bad
        );
    }
}

#[tokio::test]
async fn quiet_requires_registration() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    let mut outbox = Outbox::new();
    flow::cmd_quiet(&mut outbox, &pool, &cfg, &alice(), None).await.unwrap();
    assert!(outbox.reply_texts()[0].contains("/register"));
}

#[tokio::test]
async fn loud_clears_active_mute() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    repo::set_mute(
        &pool,
        1,
        Some(unifestbestellbot::models::now_utc() + chrono::Duration::minutes(30)),
    )
    .await
    .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_loud(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    assert!(repo::registration_for(&pool, 1)
        .await
        .unwrap()
        .unwrap()
        .mute_peer_until
        .is_none());
    assert!(outbox.reply_texts()[0].contains("🔔"));
}

#[tokio::test]
async fn loud_is_idempotent_when_already_loud() {
    let pool = test_pool().await;
    let cfg = common::test_config();
    repo::upsert_registration(&pool, &Registration::new(1, "Cocktailbar 1"))
        .await
        .unwrap();
    let mut outbox = Outbox::new();
    flow::cmd_loud(&mut outbox, &pool, &cfg, &alice()).await.unwrap();
    assert!(outbox.reply_texts()[0].contains("nicht ausgeschaltet"));
}
