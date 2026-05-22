//! Binary entrypoint. Spawns the teloxide poller, the axum dashboard,
//! and (when enabled) the Engelsystem shift digest in one tokio
//! runtime. Ctrl-C drops out of `select!` and the cleanup awaits run.

use std::sync::Arc;

use anyhow::Result;
use unifestbestellbot::bot::adapter::{run as run_bot, AdapterCtx};
use unifestbestellbot::config::AppConfig;
use unifestbestellbot::engelsystem::EngelsystemClient;
use unifestbestellbot::events::EventBus;
use unifestbestellbot::settings::Settings;
use unifestbestellbot::{bot, db, i18n, logging, web};

#[tokio::main]
async fn main() -> Result<()> {
    let _ = dotenvy::dotenv();
    let settings = Arc::new(Settings::from_env()?);

    let _log_guard = logging::setup_logging(
        &settings.log_level,
        std::path::Path::new(&settings.log_dir),
    )?;
    tracing::info!(
        "UnifestBestellBot starting from {}",
        hostname()
    );

    let cfg_path = settings.config_path.clone();
    let config = Arc::new(AppConfig::load(&cfg_path)?);

    let pool = db::pool_from_url(&settings.database_url).await?;
    db::init_schema(&pool).await?;

    let events = EventBus::new();
    let engelsystem = if !settings.engelsystem_api_key.is_empty() {
        Some(Arc::new(EngelsystemClient::new(
            &settings.engelsystem_base_url,
            &settings.engelsystem_api_key,
        )))
    } else {
        None
    };

    let adapter_ctx = AdapterCtx {
        pool: pool.clone(),
        config: config.clone(),
        events: events.clone(),
        engelsystem: engelsystem.clone(),
        settings: settings.clone(),
    };

    // Startup channel post — best-effort.
    {
        use teloxide::prelude::*;
        let bot = teloxide::Bot::new(&settings.telegram_token);
        if let Err(e) = bot
            .send_message(
                teloxide::types::ChatId(settings.updates_channel_id),
                i18n::ch_bot_started(&hostname()),
            )
            .await
        {
            tracing::warn!("startup channel post failed: {}", e);
        }
    }

    // Axum dashboard.
    let state = web::AppState {
        pool: pool.clone(),
        events: events.clone(),
    };
    let static_dir =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/static");
    let app = web::build_app(state, static_dir);
    let addr: std::net::SocketAddr = settings.web_bind.parse()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!("dashboard listening on http://{}", addr);
    let web_task = tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, app).await {
            tracing::error!("web server stopped: {}", e);
        }
    });

    // Optional shift digest loop.
    let digest_task = if config.shift_digest.enabled {
        match engelsystem.as_ref() {
            Some(client) => {
                let client = (**client).clone();
                let pool = pool.clone();
                let config = (*config).clone();
                Some(tokio::spawn(async move {
                    if let Err(e) =
                        bot::digest::shift_digest_loop(pool, config, client).await
                    {
                        tracing::error!("digest loop stopped: {}", e);
                    }
                }))
            }
            None => {
                tracing::warn!(
                    "shift_digest.enabled=true but ENGELSYSTEM_API_KEY is empty; \
                     digest will not run"
                );
                None
            }
        }
    } else {
        None
    };

    // Run the bot. Ctrl-C handled by teloxide's enable_ctrlc_handler.
    let bot_result = run_bot(adapter_ctx).await;

    // Cleanup: drop the bus (closes SSE subscribers), abort background
    // tasks. drop(_log_guard) at end of main flushes the file appender.
    drop(events);
    if let Some(t) = digest_task {
        t.abort();
    }
    web_task.abort();

    bot_result
}

fn hostname() -> String {
    std::env::var("HOSTNAME")
        .ok()
        .or_else(|| {
            std::process::Command::new("hostname")
                .output()
                .ok()
                .and_then(|o| String::from_utf8(o.stdout).ok())
                .map(|s| s.trim().to_string())
        })
        .unwrap_or_else(|| "unknown".to_string())
}
