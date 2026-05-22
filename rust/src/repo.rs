//! Data-access layer. Mirrors the Python `repo.py` function set; each
//! call commits its own changes and writes a matching audit-log row in
//! the same transaction.

use chrono::NaiveDateTime;
use serde_json::json;
use sqlx::{Row, SqlitePool};
use thiserror::Error;

use crate::models::{now_utc, AuditEvent, Registration, Ticket, TicketStatus};

#[derive(Debug, Error)]
pub enum RepoError {
    #[error("sqlx: {0}")]
    Sqlx(#[from] sqlx::Error),
    #[error("ticket {0} does not exist")]
    NotFound(i64),
    #[error("invalid transition: {0}")]
    InvalidTransition(String),
}

// --- Registration --------------------------------------------------------

pub async fn upsert_registration(
    pool: &SqlitePool,
    reg: &Registration,
) -> Result<Registration, RepoError> {
    let mut tx = pool.begin().await?;

    let previous: Option<String> = sqlx::query_scalar(
        "SELECT group_name FROM registration WHERE chat_id = ?",
    )
    .bind(reg.chat_id)
    .fetch_optional(&mut *tx)
    .await?;

    sqlx::query(
        r#"INSERT INTO registration
            (chat_id, group_name, username, first_name, last_name, registered_at, mute_peer_until)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET
             group_name = excluded.group_name,
             username   = excluded.username,
             first_name = excluded.first_name,
             last_name  = excluded.last_name"#,
    )
    .bind(reg.chat_id)
    .bind(&reg.group_name)
    .bind(&reg.username)
    .bind(&reg.first_name)
    .bind(&reg.last_name)
    .bind(reg.registered_at)
    .bind(reg.mute_peer_until)
    .execute(&mut *tx)
    .await?;

    let payload = match previous {
        Some(p) => json!({"group_name": reg.group_name, "previous": p}),
        None => json!({"group_name": reg.group_name}),
    };
    write_audit(&mut tx, "register", None, Some(reg.chat_id), Some(payload)).await?;
    tx.commit().await?;

    Ok(registration_for(pool, reg.chat_id)
        .await?
        .expect("just inserted"))
}

pub async fn unregister(pool: &SqlitePool, chat_id: i64) -> Result<Option<String>, RepoError> {
    let mut tx = pool.begin().await?;
    let group: Option<String> =
        sqlx::query_scalar("SELECT group_name FROM registration WHERE chat_id = ?")
            .bind(chat_id)
            .fetch_optional(&mut *tx)
            .await?;
    let Some(group) = group else {
        return Ok(None);
    };
    sqlx::query("DELETE FROM registration WHERE chat_id = ?")
        .bind(chat_id)
        .execute(&mut *tx)
        .await?;
    write_audit(
        &mut tx,
        "unregister",
        None,
        Some(chat_id),
        Some(json!({"group_name": group})),
    )
    .await?;
    tx.commit().await?;
    Ok(Some(group))
}

pub async fn registration_for(
    pool: &SqlitePool,
    chat_id: i64,
) -> Result<Option<Registration>, RepoError> {
    let row = sqlx::query(
        r#"SELECT chat_id, group_name, username, first_name, last_name, registered_at,
                  mute_peer_until
             FROM registration
            WHERE chat_id = ?"#,
    )
    .bind(chat_id)
    .fetch_optional(pool)
    .await?;
    Ok(row.map(row_to_registration))
}

pub async fn group_members(
    pool: &SqlitePool,
    group_name: &str,
    exclude_muted: bool,
) -> Result<Vec<i64>, RepoError> {
    let rows = if exclude_muted {
        let now = now_utc();
        sqlx::query_scalar::<_, i64>(
            r#"SELECT chat_id FROM registration
                WHERE group_name = ?
                  AND (mute_peer_until IS NULL OR mute_peer_until <= ?)"#,
        )
        .bind(group_name)
        .bind(now)
        .fetch_all(pool)
        .await?
    } else {
        sqlx::query_scalar::<_, i64>(
            "SELECT chat_id FROM registration WHERE group_name = ?",
        )
        .bind(group_name)
        .fetch_all(pool)
        .await?
    };
    Ok(rows)
}

pub async fn set_mute(
    pool: &SqlitePool,
    chat_id: i64,
    until: Option<NaiveDateTime>,
) -> Result<bool, RepoError> {
    let result = sqlx::query("UPDATE registration SET mute_peer_until = ? WHERE chat_id = ?")
        .bind(until)
        .bind(chat_id)
        .execute(pool)
        .await?;
    Ok(result.rows_affected() > 0)
}

// --- Tickets -------------------------------------------------------------

pub async fn create_ticket(
    pool: &SqlitePool,
    category: &str,
    text: &str,
    group_requesting: &str,
    group_tasked: &str,
    actor_chat_id: i64,
) -> Result<Ticket, RepoError> {
    let mut tx = pool.begin().await?;
    let created_at = now_utc();

    let result = sqlx::query(
        r#"INSERT INTO ticket
            (status, category, text, group_requesting, group_tasked, created_at)
           VALUES (?, ?, ?, ?, ?, ?)"#,
    )
    .bind(TicketStatus::Open.as_str())
    .bind(category)
    .bind(text)
    .bind(group_requesting)
    .bind(group_tasked)
    .bind(created_at)
    .execute(&mut *tx)
    .await?;

    let id = result.last_insert_rowid();
    write_audit(&mut tx, "open", Some(id), Some(actor_chat_id), None).await?;
    tx.commit().await?;

    Ok(get_ticket(pool, id).await?.expect("just inserted"))
}

pub async fn set_wip(
    pool: &SqlitePool,
    ticket_id: i64,
    who: &str,
    actor_chat_id: i64,
) -> Result<Ticket, RepoError> {
    let mut tx = pool.begin().await?;
    let ticket = fetch_ticket_in_tx(&mut tx, ticket_id).await?;
    if ticket.status != TicketStatus::Open {
        return Err(RepoError::InvalidTransition(format!(
            "ticket {} is not open (status={})",
            ticket_id, ticket.status
        )));
    }
    sqlx::query("UPDATE ticket SET status = ?, who_wip = ? WHERE id = ?")
        .bind(TicketStatus::Wip.as_str())
        .bind(who)
        .bind(ticket_id)
        .execute(&mut *tx)
        .await?;
    write_audit(
        &mut tx,
        "wip",
        Some(ticket_id),
        Some(actor_chat_id),
        Some(json!({"who": who})),
    )
    .await?;
    tx.commit().await?;
    Ok(get_ticket(pool, ticket_id).await?.expect("just updated"))
}

pub async fn close_ticket(
    pool: &SqlitePool,
    ticket_id: i64,
    actor_chat_id: i64,
) -> Result<Ticket, RepoError> {
    let mut tx = pool.begin().await?;
    let ticket = fetch_ticket_in_tx(&mut tx, ticket_id).await?;
    if ticket.status == TicketStatus::Closed {
        return Err(RepoError::InvalidTransition(format!(
            "ticket {} is already closed",
            ticket_id
        )));
    }
    let closed_at = now_utc();
    sqlx::query("UPDATE ticket SET status = ?, closed_at = ? WHERE id = ?")
        .bind(TicketStatus::Closed.as_str())
        .bind(closed_at)
        .bind(ticket_id)
        .execute(&mut *tx)
        .await?;
    write_audit(&mut tx, "close", Some(ticket_id), Some(actor_chat_id), None).await?;
    tx.commit().await?;
    Ok(get_ticket(pool, ticket_id).await?.expect("just updated"))
}

pub async fn move_ticket(
    pool: &SqlitePool,
    ticket_id: i64,
    new_group: &str,
    actor_chat_id: i64,
) -> Result<Ticket, RepoError> {
    let mut tx = pool.begin().await?;
    let ticket = fetch_ticket_in_tx(&mut tx, ticket_id).await?;
    if ticket.status != TicketStatus::Open {
        return Err(RepoError::InvalidTransition(format!(
            "ticket {} is not open (status={})",
            ticket_id, ticket.status
        )));
    }
    let previous = ticket.group_tasked.clone();
    sqlx::query("UPDATE ticket SET group_tasked = ? WHERE id = ?")
        .bind(new_group)
        .bind(ticket_id)
        .execute(&mut *tx)
        .await?;
    write_audit(
        &mut tx,
        "move",
        Some(ticket_id),
        Some(actor_chat_id),
        Some(json!({"from": previous, "to": new_group})),
    )
    .await?;
    tx.commit().await?;
    Ok(get_ticket(pool, ticket_id).await?.expect("just updated"))
}

pub async fn get_ticket(pool: &SqlitePool, ticket_id: i64) -> Result<Option<Ticket>, RepoError> {
    let row = sqlx::query(
        r#"SELECT id, status, category, text, group_requesting, group_tasked,
                  who_wip, created_at, closed_at
             FROM ticket
            WHERE id = ?"#,
    )
    .bind(ticket_id)
    .fetch_optional(pool)
    .await?;
    Ok(row.map(row_to_ticket))
}

pub async fn active_tickets(
    pool: &SqlitePool,
    group_tasked: Option<&str>,
    status: Option<TicketStatus>,
) -> Result<Vec<Ticket>, RepoError> {
    let base = r#"SELECT id, status, category, text, group_requesting, group_tasked,
                         who_wip, created_at, closed_at
                    FROM ticket
                   WHERE status != ?"#;
    let mut q = String::from(base);
    if group_tasked.is_some() {
        q.push_str(" AND group_tasked = ?");
    }
    if status.is_some() {
        q.push_str(" AND status = ?");
    }
    q.push_str(" ORDER BY id");

    let mut query = sqlx::query(&q).bind(TicketStatus::Closed.as_str());
    if let Some(g) = group_tasked {
        query = query.bind(g);
    }
    if let Some(s) = status {
        query = query.bind(s.as_str());
    }
    let rows = query.fetch_all(pool).await?;
    Ok(rows.into_iter().map(row_to_ticket).collect())
}

pub async fn tickets_requested_by(
    pool: &SqlitePool,
    group: &str,
) -> Result<Vec<Ticket>, RepoError> {
    let rows = sqlx::query(
        r#"SELECT id, status, category, text, group_requesting, group_tasked,
                  who_wip, created_at, closed_at
             FROM ticket
            WHERE group_requesting = ? AND status != ?
            ORDER BY id"#,
    )
    .bind(group)
    .bind(TicketStatus::Closed.as_str())
    .fetch_all(pool)
    .await?;
    Ok(rows.into_iter().map(row_to_ticket).collect())
}

pub async fn record_message(
    pool: &SqlitePool,
    ticket_id: i64,
    actor_chat_id: i64,
    message: &str,
) -> Result<(), RepoError> {
    let mut tx = pool.begin().await?;
    write_audit(
        &mut tx,
        "message",
        Some(ticket_id),
        Some(actor_chat_id),
        Some(json!({"message": message})),
    )
    .await?;
    tx.commit().await?;
    Ok(())
}

// --- Recent closes (for /history) ----------------------------------------

#[derive(Debug, Clone)]
pub struct CloseSummary {
    pub ticket: Ticket,
    pub closed_at: NaiveDateTime,
    pub closer_chat_id: Option<i64>,
    pub closer_display: String,
}

pub async fn recent_closes(
    pool: &SqlitePool,
    group_tasked: Option<&str>,
    limit: i64,
) -> Result<Vec<CloseSummary>, RepoError> {
    let mut q = String::from(
        r#"SELECT t.id, t.status, t.category, t.text, t.group_requesting, t.group_tasked,
                  t.who_wip, t.created_at, t.closed_at,
                  e.ts AS event_ts, e.actor_chat_id AS event_actor
             FROM ticket t
             JOIN auditevent e ON e.ticket_id = t.id
            WHERE t.status = ? AND e.kind = ?"#,
    );
    if group_tasked.is_some() {
        q.push_str(" AND t.group_tasked = ?");
    }
    q.push_str(" ORDER BY e.ts DESC LIMIT ?");

    let mut query = sqlx::query(&q)
        .bind(TicketStatus::Closed.as_str())
        .bind("close");
    if let Some(g) = group_tasked {
        query = query.bind(g);
    }
    query = query.bind(limit);

    let rows = query.fetch_all(pool).await?;

    let mut out = Vec::with_capacity(rows.len());
    for row in rows {
        let event_ts: NaiveDateTime = row.try_get("event_ts")?;
        let event_actor: Option<i64> = row.try_get("event_actor")?;
        let ticket = row_to_ticket(row);
        let closer_display = match event_actor {
            Some(cid) => match registration_for(pool, cid).await? {
                Some(reg) => reg.display_name(),
                None => format!("chat {}", cid),
            },
            None => "Unbekannt".to_string(),
        };
        out.push(CloseSummary {
            ticket,
            closed_at: event_ts,
            closer_chat_id: event_actor,
            closer_display,
        });
    }
    Ok(out)
}

// --- Audit listing (for tests) -------------------------------------------

pub async fn all_audit(pool: &SqlitePool) -> Result<Vec<AuditEvent>, RepoError> {
    let rows = sqlx::query(
        "SELECT id, ts, kind, ticket_id, actor_chat_id, payload_json FROM auditevent ORDER BY id",
    )
    .fetch_all(pool)
    .await?;
    Ok(rows
        .into_iter()
        .map(|r| AuditEvent {
            id: r.get("id"),
            ts: r.get("ts"),
            kind: r.get("kind"),
            ticket_id: r.get("ticket_id"),
            actor_chat_id: r.get("actor_chat_id"),
            payload_json: r.get("payload_json"),
        })
        .collect())
}

// --- Internals -----------------------------------------------------------

async fn fetch_ticket_in_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    ticket_id: i64,
) -> Result<Ticket, RepoError> {
    let row = sqlx::query(
        r#"SELECT id, status, category, text, group_requesting, group_tasked,
                  who_wip, created_at, closed_at
             FROM ticket
            WHERE id = ?"#,
    )
    .bind(ticket_id)
    .fetch_optional(&mut **tx)
    .await?;
    row.map(row_to_ticket).ok_or(RepoError::NotFound(ticket_id))
}

async fn write_audit(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    kind: &str,
    ticket_id: Option<i64>,
    actor_chat_id: Option<i64>,
    payload: Option<serde_json::Value>,
) -> Result<(), RepoError> {
    let payload_json = payload.map(|v| v.to_string());
    sqlx::query(
        "INSERT INTO auditevent (ts, kind, ticket_id, actor_chat_id, payload_json)
         VALUES (?, ?, ?, ?, ?)",
    )
    .bind(now_utc())
    .bind(kind)
    .bind(ticket_id)
    .bind(actor_chat_id)
    .bind(payload_json)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

fn row_to_registration(row: sqlx::sqlite::SqliteRow) -> Registration {
    Registration {
        chat_id: row.get("chat_id"),
        group_name: row.get("group_name"),
        username: row.get("username"),
        first_name: row.get("first_name"),
        last_name: row.get("last_name"),
        registered_at: row.get("registered_at"),
        mute_peer_until: row.get("mute_peer_until"),
    }
}

fn row_to_ticket(row: sqlx::sqlite::SqliteRow) -> Ticket {
    let status_str: String = row.get("status");
    let status = TicketStatus::parse(&status_str).expect("known status");
    Ticket {
        id: row.get("id"),
        status,
        category: row.get("category"),
        text: row.get("text"),
        group_requesting: row.get("group_requesting"),
        group_tasked: row.get("group_tasked"),
        who_wip: row.get("who_wip"),
        created_at: row.get("created_at"),
        closed_at: row.get("closed_at"),
    }
}
