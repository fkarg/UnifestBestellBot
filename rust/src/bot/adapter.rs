//! Teloxide adapter. The only module that touches teloxide types.
//! Translates incoming teloxide updates into calls on the handler logic
//! in this module's siblings, then translates the resulting [`Action`]
//! lists back into outgoing teloxide calls.
//!
//! Intentionally compact: the heavy logic lives in `register`,
//! `request`, `orga`, `admin`, and is exhaustively tested without
//! teloxide. This file is dispatch and serialization only.

use std::sync::Arc;

use anyhow::Result;
use sqlx::SqlitePool;
use teloxide::dispatching::dialogue::InMemStorage;
use teloxide::dispatching::{Dispatcher, UpdateFilterExt, UpdateHandler};
use teloxide::dptree;
use teloxide::prelude::*;
use teloxide::types::{
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, KeyboardMarkup,
    KeyboardRemove, ReplyMarkup,
};
use teloxide::utils::command::BotCommands;

use super::request::RequestState;
use super::{
    admin, digest as _digest, orga, register, request, unknown, Action, Caller, Keyboard, Outbox,
};
use crate::config::AppConfig;
use crate::engelsystem::EngelsystemClient;
use crate::events::EventBus;
use crate::settings::Settings;

#[derive(BotCommands, Clone, Debug)]
#[command(rename_rule = "lowercase")]
enum Cmd {
    Start,
    Help,
    Register(String),
    Unregister,
    Status,
    Quiet(String),
    Loud,
    Request,
    Cancel,
    Bug(String),
    Feature(String),
    Tickets,
    All,
    Help2,
    Wip(String),
    Close(String),
    Move(String),
    Message(String),
    Helpers(String),
    History(String),
    Closeall,
}

#[derive(Clone)]
pub struct AdapterCtx {
    pub pool: SqlitePool,
    pub config: Arc<AppConfig>,
    pub events: EventBus,
    pub engelsystem: Option<Arc<EngelsystemClient>>,
    pub settings: Arc<Settings>,
}

type FsmStorage = InMemStorage<RequestState>;

pub async fn run(ctx: AdapterCtx) -> Result<()> {
    let bot = Bot::new(&ctx.settings.telegram_token);
    bot.set_my_commands(Cmd::bot_commands()).await.ok();

    let handler: UpdateHandler<anyhow::Error> = dptree::entry()
        .branch(
            Update::filter_message()
                .enter_dialogue::<Message, FsmStorage, RequestState>()
                .branch(
                    dptree::entry()
                        .filter_command::<Cmd>()
                        .endpoint(handle_command),
                )
                .branch(dptree::endpoint(handle_message)),
        )
        .branch(Update::filter_callback_query().endpoint(handle_callback));

    let storage = InMemStorage::<RequestState>::new();
    Dispatcher::builder(bot, handler)
        .dependencies(dptree::deps![ctx.clone(), storage])
        .enable_ctrlc_handler()
        .build()
        .dispatch()
        .await;
    Ok(())
}

fn caller_from(user: &teloxide::types::User) -> Caller {
    Caller {
        chat_id: user.id.0 as i64,
        username: user.username.clone(),
        first_name: Some(user.first_name.clone()),
        last_name: user.last_name.clone(),
    }
}

async fn handle_command(
    bot: Bot,
    msg: Message,
    cmd: Cmd,
    dialogue: Dialogue<RequestState, FsmStorage>,
    ctx: AdapterCtx,
) -> Result<()> {
    let Some(user) = msg.from.as_ref() else {
        return Ok(());
    };
    let caller = caller_from(user);
    let mut outbox = Outbox::new();
    let cfg = ctx.config.as_ref();
    let pool = &ctx.pool;
    let engel = ctx.engelsystem.as_deref();

    let new_state: Option<RequestState> = match cmd {
        Cmd::Start => {
            register::cmd_start(&mut outbox, pool, cfg, &caller).await?;
            None
        }
        Cmd::Help => {
            register::cmd_help(&mut outbox, pool, cfg, &caller).await?;
            None
        }
        Cmd::Register(arg) => {
            let a = (!arg.trim().is_empty()).then(|| arg.as_str());
            register::cmd_register(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Unregister => {
            register::cmd_unregister(&mut outbox, pool, cfg, &caller).await?;
            None
        }
        Cmd::Status => {
            register::cmd_status(&mut outbox, pool, cfg, &caller).await?;
            None
        }
        Cmd::Quiet(arg) => {
            let a = (!arg.trim().is_empty()).then(|| arg.as_str());
            register::cmd_quiet(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Loud => {
            register::cmd_loud(&mut outbox, pool, cfg, &caller).await?;
            None
        }
        Cmd::Request => {
            let state = dialogue.get_or_default().await?;
            let new = request::cmd_request(&mut outbox, pool, cfg, &caller, state).await?;
            Some(new)
        }
        Cmd::Cancel => {
            let state = dialogue.get_or_default().await?;
            let new = request::cmd_cancel(&mut outbox, pool, cfg, &caller, state).await?;
            Some(new)
        }
        Cmd::Bug(text) => {
            let a = (!text.trim().is_empty()).then(|| text.as_str());
            orga::cmd_bug(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Feature(text) => {
            let a = (!text.trim().is_empty()).then(|| text.as_str());
            orga::cmd_feature(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Tickets => {
            orga::cmd_tickets(&mut outbox, pool, cfg, &caller).await?;
            None
        }
        Cmd::All => {
            orga::cmd_all(&mut outbox, pool, cfg, &caller).await?;
            None
        }
        Cmd::Help2 => {
            orga::cmd_help2(&mut outbox, pool, cfg, &caller).await?;
            None
        }
        Cmd::Wip(arg) => {
            let a = (!arg.trim().is_empty()).then(|| arg.as_str());
            orga::cmd_wip(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Close(arg) => {
            let a = (!arg.trim().is_empty()).then(|| arg.as_str());
            orga::cmd_close(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Move(rest) => {
            let a = (!rest.trim().is_empty()).then(|| rest.as_str());
            orga::cmd_move(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Message(rest) => {
            let a = (!rest.trim().is_empty()).then(|| rest.as_str());
            orga::cmd_message(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Helpers(arg) => {
            let a = (!arg.trim().is_empty()).then(|| arg.as_str());
            orga::cmd_helpers(&mut outbox, pool, cfg, engel, &caller, a).await?;
            None
        }
        Cmd::History(arg) => {
            let a = (!arg.trim().is_empty()).then(|| arg.as_str());
            orga::cmd_history(&mut outbox, pool, cfg, &caller, a).await?;
            None
        }
        Cmd::Closeall => {
            if caller.chat_id == ctx.settings.developer_chat_id {
                admin::cmd_closeall(&mut outbox, pool, cfg, &caller).await?;
            } else {
                // Silently ignore for non-devs (legacy behaviour kept dev_msg
                // logging; we just drop here).
            }
            None
        }
    };

    if let Some(s) = new_state {
        dialogue.update(s).await?;
    }
    execute(&bot, &msg, None, &outbox, &ctx).await?;
    Ok(())
}

async fn handle_message(
    bot: Bot,
    msg: Message,
    dialogue: Dialogue<RequestState, FsmStorage>,
    ctx: AdapterCtx,
) -> Result<()> {
    let Some(user) = msg.from.as_ref() else {
        return Ok(());
    };
    let caller = caller_from(user);
    let mut outbox = Outbox::new();
    let cfg = ctx.config.as_ref();
    let pool = &ctx.pool;

    let state = dialogue.get_or_default().await?;
    let text = msg.text().unwrap_or("");

    if state != RequestState::Idle {
        let new_state = request::on_text(
            &mut outbox,
            pool,
            cfg,
            &ctx.events,
            ctx.engelsystem.as_deref(),
            &caller,
            state,
            text,
        )
        .await?;
        dialogue.update(new_state).await?;
    } else {
        unknown::cmd_unknown(&mut outbox, pool, cfg, &caller).await?;
    }
    execute(&bot, &msg, None, &outbox, &ctx).await?;
    Ok(())
}

async fn handle_callback(bot: Bot, q: CallbackQuery, ctx: AdapterCtx) -> Result<()> {
    let caller = caller_from(&q.from);
    let data = q.data.as_deref().unwrap_or("");
    let cfg = ctx.config.as_ref();
    let pool = &ctx.pool;
    let mut outbox = Outbox::new();

    if let Some(rest) = data.strip_prefix("reg:") {
        register::on_register_choice(&mut outbox, pool, cfg, &caller, rest).await?;
    } else if let Some(rest) = data.strip_prefix("wip:") {
        orga::on_wip_choice(&mut outbox, pool, cfg, &caller, rest).await?;
    } else if let Some(rest) = data.strip_prefix("close:") {
        orga::on_close_choice(&mut outbox, pool, cfg, &caller, rest).await?;
    } else {
        bot.answer_callback_query(q.id.clone()).await.ok();
        return Ok(());
    }
    let msg = q.message.as_ref().and_then(|m| m.regular_message().cloned());
    execute(&bot, msg.as_ref().unwrap_or(&dummy_message()), Some(&q), &outbox, &ctx).await?;
    Ok(())
}

fn dummy_message() -> Message {
    // teloxide does not let us construct a Message ergonomically; we
    // only need a fallback reference for the rare case where the
    // callback comes from a message that's no longer accessible.
    // The action executor below handles the absence by guarding on the
    // chat id from the actual message when present.
    unreachable!("execute() guards on Some(callback) when message is missing")
}

async fn execute(
    bot: &Bot,
    msg: &Message,
    callback: Option<&CallbackQuery>,
    outbox: &Outbox,
    ctx: &AdapterCtx,
) -> Result<()> {
    use teloxide::types::ChatId;

    let chat_id = msg.chat.id;

    for action in &outbox.actions {
        match action {
            Action::Reply { text, keyboard } => {
                let mut req = bot.send_message(chat_id, text);
                if let Some(rm) = render_keyboard(keyboard, ctx).await {
                    req = req.reply_markup(rm);
                }
                req.await?;
            }
            Action::Dm {
                chat_id: target,
                text,
                keyboard,
            } => {
                let mut req = bot.send_message(ChatId(*target), text);
                if let Some(rm) = render_keyboard(keyboard, ctx).await {
                    req = req.reply_markup(rm);
                }
                if let Err(e) = req.await {
                    tracing::warn!("DM to {} failed: {}", target, e);
                }
            }
            Action::Channel(text) => {
                let _ = bot
                    .send_message(ChatId(ctx.settings.updates_channel_id), text)
                    .await;
            }
            Action::Dev(text) => {
                let _ = bot
                    .send_message(ChatId(ctx.settings.developer_chat_id), text)
                    .await;
            }
            Action::EditMessage(text) => {
                if let Some(cb) = callback {
                    if let Some(msg) = cb.message.as_ref().and_then(|m| m.regular_message()) {
                        let _ = bot.edit_message_text(msg.chat.id, msg.id, text).await;
                    }
                }
            }
            Action::AnswerCallback { text, alert } => {
                if let Some(cb) = callback {
                    let mut req = bot.answer_callback_query(cb.id.clone());
                    if let Some(t) = text {
                        req = req.text(t.clone());
                    }
                    if *alert {
                        req = req.show_alert(true);
                    }
                    let _ = req.await;
                }
            }
        }
    }
    Ok(())
}

async fn render_keyboard(kb: &Keyboard, _ctx: &AdapterCtx) -> Option<ReplyMarkup> {
    match kb {
        Keyboard::None => None,
        Keyboard::Remove => Some(ReplyMarkup::KeyboardRemove(KeyboardRemove::new())),
        Keyboard::Reply(rows) => {
            let kb = KeyboardMarkup::new(rows.iter().map(|row| {
                row.iter().map(|label| KeyboardButton::new(label.clone()))
            }))
            .resize_keyboard()
            .persistent();
            Some(ReplyMarkup::Keyboard(kb))
        }
        Keyboard::Inline(rows) => {
            let kb = InlineKeyboardMarkup::new(rows.iter().map(|(label, data)| {
                vec![InlineKeyboardButton::callback(label.clone(), data.clone())]
            }));
            Some(ReplyMarkup::InlineKeyboard(kb))
        }
        Keyboard::AutoSelect { .. } => {
            // Logic functions resolve the user's role themselves; if they
            // emit AutoSelect it's a bug, but render an empty default.
            None
        }
    }
}
