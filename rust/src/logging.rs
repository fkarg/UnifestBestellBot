//! Coloured terminal output + daily-rotating file. Matches the Python
//! `logging_setup.setup_logging` behaviour: terminal for the operator
//! watching the tmux pane, plain-text rotating file for archive.

use std::path::Path;
use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::{fmt, prelude::*, EnvFilter, Registry};

/// Hold onto the returned guard for the lifetime of the program;
/// dropping it flushes the file appender.
pub fn setup_logging(level: &str, log_dir: &Path) -> anyhow::Result<WorkerGuard> {
    std::fs::create_dir_all(log_dir)?;

    let env_filter = EnvFilter::try_new(level).unwrap_or_else(|_| EnvFilter::new("info"));

    let stderr_layer = fmt::layer()
        .with_target(true)
        .with_ansi(true)
        .with_timer(fmt::time::ChronoLocal::new("%H:%M:%S".into()));

    let file_appender = tracing_appender::rolling::daily(log_dir, "bot.log");
    let (file_writer, guard) = tracing_appender::non_blocking(file_appender);
    let file_layer = fmt::layer()
        .with_target(true)
        .with_ansi(false)
        .with_writer(file_writer)
        .with_timer(fmt::time::ChronoLocal::new("%Y-%m-%d %H:%M:%S".into()));

    Registry::default()
        .with(env_filter)
        .with(stderr_layer)
        .with(file_layer)
        .init();

    Ok(guard)
}
