//! Environment-backed runtime settings. The set of variables matches
//! the Python `.env.example` so a single `.env` file works for either
//! implementation.

use std::env;
use thiserror::Error;

#[derive(Debug, Clone)]
pub struct Settings {
    pub telegram_token: String,
    pub developer_chat_id: i64,
    pub updates_channel_id: i64,
    pub engelsystem_api_key: String,
    pub engelsystem_base_url: String,
    pub database_url: String,
    pub config_path: String,
    pub web_bind: String,
    pub log_level: String,
    pub log_dir: String,
    pub log_retention_days: u16,
}

#[derive(Debug, Error)]
pub enum SettingsError {
    #[error("missing required env var: {0}")]
    Missing(&'static str),
    #[error("env var {0} is not a valid integer: {1}")]
    BadInt(&'static str, std::num::ParseIntError),
}

fn required(name: &'static str) -> Result<String, SettingsError> {
    env::var(name).map_err(|_| SettingsError::Missing(name))
}

fn optional(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_string())
}

fn required_int<T: std::str::FromStr<Err = std::num::ParseIntError>>(
    name: &'static str,
) -> Result<T, SettingsError> {
    let s = required(name)?;
    s.parse::<T>().map_err(|e| SettingsError::BadInt(name, e))
}

impl Settings {
    /// Load from process environment. `.env` is loaded by the caller
    /// (typically `main`) before this runs.
    pub fn from_env() -> Result<Self, SettingsError> {
        Ok(Settings {
            telegram_token: required("TELEGRAM_TOKEN")?,
            developer_chat_id: required_int("DEVELOPER_CHAT_ID")?,
            updates_channel_id: required_int("UPDATES_CHANNEL_ID")?,
            engelsystem_api_key: optional("ENGELSYSTEM_API_KEY", ""),
            engelsystem_base_url: optional(
                "ENGELSYSTEM_BASE_URL",
                "https://helfen.unifest-karlsruhe.de/api/v0-beta/",
            ),
            database_url: optional("DATABASE_URL", "sqlite://./bot.db"),
            config_path: optional("CONFIG_PATH", "./config.yaml"),
            web_bind: optional("WEB_BIND", "0.0.0.0:8000"),
            log_level: optional("LOG_LEVEL", "INFO"),
            log_dir: optional("LOG_DIR", "./logs"),
            log_retention_days: optional("LOG_RETENTION_DAYS", "14")
                .parse()
                .unwrap_or(14),
        })
    }
}
