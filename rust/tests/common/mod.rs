//! Shared test helpers.

use unifestbestellbot::config::AppConfig;
use unifestbestellbot::repo;

/// The canonical test config. Mirrors `tests/conftest.py::config` on the
/// Python side so behaviour tests can be cross-read.
pub fn test_config() -> AppConfig {
    let yaml = r#"
stalls:
  - name: "Cocktailbar 1"
    location: "Innenhof"
    type: "Cocktail"
  - name: "Biertheke 1"
    location: "Außenbereich"
    type: "Bier"
  - name: "Tickets"
    location: "Eingang"
    type: "Tickets"
    hidden: true

orga_groups:
  - name: "Finanz"
    categories: ["Geld"]
  - name: "BiMi"
    categories: ["Bier", "Cocktail", "Becher"]
  - name: "Helfen"
    categories: ["Helfer"]
  - name: "Zentrale"
    categories: ["Sonstiges"]
    default: true

locations:
  "Innenhof": 12
  "Außenbereich": 15
"#;
    let cfg: AppConfig = serde_yaml::from_str(yaml).expect("yaml");
    cfg.validate().expect("invariants");
    cfg
}

#[allow(dead_code)]
pub async fn open_ticket(
    pool: &sqlx::SqlitePool,
    text: &str,
    group_requesting: &str,
    group_tasked: &str,
) -> unifestbestellbot::models::Ticket {
    repo::create_ticket(pool, "Geld", text, group_requesting, group_tasked, 5)
        .await
        .expect("create_ticket")
}
