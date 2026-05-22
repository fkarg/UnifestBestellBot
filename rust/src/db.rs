//! SQLite engine + schema bootstrap. The schema is identical to what
//! the Python `SQLModel.metadata.create_all` produces so a `bot.db`
//! file is interchangeable between the two implementations.

use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions};
use sqlx::SqlitePool;
use std::str::FromStr;

/// Create a pool against `database_url`. Accepts both `sqlite://./bot.db`
/// and the in-memory `sqlite::memory:` forms.
pub async fn pool_from_url(database_url: &str) -> anyhow::Result<SqlitePool> {
    // Strip the `sqlite://` prefix sqlx expects when handing the URL to
    // SqliteConnectOptions, which uses raw filesystem paths.
    let raw = database_url
        .strip_prefix("sqlite://")
        .unwrap_or(database_url);

    let opts = SqliteConnectOptions::from_str(raw)?
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .foreign_keys(true);

    let pool = SqlitePoolOptions::new()
        .max_connections(8)
        .connect_with(opts)
        .await?;

    Ok(pool)
}

/// Idempotent table creation. Equivalent to
/// `SQLModel.metadata.create_all` on the Python side; the column names
/// and types are chosen so both implementations can open the same DB.
pub async fn init_schema(pool: &SqlitePool) -> anyhow::Result<()> {
    let stmts = [
        r#"CREATE TABLE IF NOT EXISTS registration (
            chat_id           INTEGER PRIMARY KEY,
            group_name        TEXT NOT NULL,
            username          TEXT,
            first_name        TEXT,
            last_name         TEXT,
            registered_at     TIMESTAMP NOT NULL,
            mute_peer_until   TIMESTAMP
        )"#,
        r#"CREATE INDEX IF NOT EXISTS ix_registration_group_name
           ON registration(group_name)"#,
        r#"CREATE TABLE IF NOT EXISTS ticket (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            status            TEXT NOT NULL,
            category          TEXT NOT NULL,
            text              TEXT NOT NULL,
            group_requesting  TEXT NOT NULL,
            group_tasked      TEXT NOT NULL,
            who_wip           TEXT,
            created_at        TIMESTAMP NOT NULL,
            closed_at         TIMESTAMP
        )"#,
        r#"CREATE INDEX IF NOT EXISTS ix_ticket_status ON ticket(status)"#,
        r#"CREATE INDEX IF NOT EXISTS ix_ticket_group_tasked ON ticket(group_tasked)"#,
        r#"CREATE TABLE IF NOT EXISTS auditevent (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TIMESTAMP NOT NULL,
            kind            TEXT NOT NULL,
            ticket_id       INTEGER REFERENCES ticket(id),
            actor_chat_id   INTEGER,
            payload_json    TEXT
        )"#,
    ];

    for stmt in stmts {
        sqlx::query(stmt).execute(pool).await?;
    }

    Ok(())
}

/// Helper for tests: an in-memory shared pool with the schema applied.
/// Public so integration tests in `tests/` can use it.
pub async fn test_pool() -> SqlitePool {
    use sqlx::sqlite::SqliteConnectOptions;
    let opts = SqliteConnectOptions::from_str(":memory:")
        .unwrap()
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Memory);
    let pool = SqlitePoolOptions::new()
        .max_connections(1) // single shared connection for in-memory
        .connect_with(opts)
        .await
        .expect("test pool");
    init_schema(&pool).await.expect("init schema");
    pool
}
