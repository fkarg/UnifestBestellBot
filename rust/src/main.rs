//! Binary entrypoint — stub for now. The bot/digest layer is added
//! once the data + web layer is green; this stub keeps the crate
//! buildable end-to-end.

use anyhow::Result;
use unifestbestellbot::{db, settings, web};

#[tokio::main]
async fn main() -> Result<()> {
    let _ = dotenvy::dotenv();
    let settings = settings::Settings::from_env()?;
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_new(&settings.log_level)
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let pool = db::pool_from_url(&settings.database_url).await?;
    db::init_schema(&pool).await?;

    let events = unifestbestellbot::events::EventBus::new();
    let state = web::AppState {
        pool: pool.clone(),
        events: events.clone(),
    };
    let static_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/static");
    let app = web::build_app(state, static_dir);

    let addr: std::net::SocketAddr = settings.web_bind.parse()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!("listening on {}", addr);
    axum::serve(listener, app).await?;

    Ok(())
}
