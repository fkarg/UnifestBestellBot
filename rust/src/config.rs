//! Year-specific configuration loaded from `config.yaml`. The schema
//! mirrors the Python `AppConfig` exactly so a single `config.yaml`
//! file is consumable by either implementation.

use chrono::NaiveTime;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::path::Path;
use thiserror::Error;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Stall {
    pub name: String,
    pub location: String,
    #[serde(rename = "type")]
    pub stall_type: String,
    #[serde(default)]
    pub hidden: bool,
}

impl Stall {
    /// How the stand appears in ticket text to orga: location first,
    /// type in brackets. Mirrors `Stall.display` in the Python config.
    pub fn display(&self) -> String {
        format!("{} [{}]", self.location, self.stall_type)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OrgaGroup {
    pub name: String,
    pub categories: Vec<String>,
    #[serde(default)]
    pub default: bool,
}

fn default_check_interval_minutes() -> u64 {
    5
}

fn default_lookahead_minutes() -> u64 {
    10
}

fn default_zero_time() -> NaiveTime {
    NaiveTime::from_hms_opt(0, 0, 0).unwrap()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ShiftDigest {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_zero_time")]
    pub window_start: NaiveTime,
    #[serde(default = "default_zero_time")]
    pub window_end: NaiveTime,
    #[serde(default = "default_check_interval_minutes")]
    pub check_interval_minutes: u64,
    #[serde(default = "default_lookahead_minutes")]
    pub lookahead_minutes: u64,
}

impl Default for ShiftDigest {
    fn default() -> Self {
        Self {
            enabled: false,
            window_start: default_zero_time(),
            window_end: default_zero_time(),
            check_interval_minutes: default_check_interval_minutes(),
            lookahead_minutes: default_lookahead_minutes(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub stalls: Vec<Stall>,
    pub orga_groups: Vec<OrgaGroup>,
    #[serde(default)]
    pub locations: HashMap<String, i32>,
    #[serde(default)]
    pub shift_digest: ShiftDigest,
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("config file: {0}")]
    Io(#[from] std::io::Error),
    #[error("config yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("config invariant: {0}")]
    Invariant(String),
}

impl AppConfig {
    /// Load and validate. The validator surfaces the same errors as the
    /// Python `_validate_invariants` so misconfiguration messages match.
    pub fn load(path: impl AsRef<Path>) -> Result<Self, ConfigError> {
        let text = std::fs::read_to_string(path)?;
        let cfg: AppConfig = serde_yaml::from_str(&text)?;
        cfg.validate()?;
        Ok(cfg)
    }

    /// Validate the same invariants as the Python config's `_validate_invariants`.
    pub fn validate(&self) -> Result<(), ConfigError> {
        let defaults: Vec<&OrgaGroup> =
            self.orga_groups.iter().filter(|g| g.default).collect();
        if defaults.len() != 1 {
            return Err(ConfigError::Invariant(format!(
                "exactly one orga_group must be marked default; found {}",
                defaults.len()
            )));
        }

        let mut orga_names = HashSet::new();
        for g in &self.orga_groups {
            if !orga_names.insert(g.name.as_str()) {
                return Err(ConfigError::Invariant("orga_groups have duplicate names".into()));
            }
        }

        let mut stall_names = HashSet::new();
        for s in &self.stalls {
            if !stall_names.insert(s.name.as_str()) {
                return Err(ConfigError::Invariant("stalls have duplicate names".into()));
            }
        }

        for name in &orga_names {
            if stall_names.contains(name) {
                return Err(ConfigError::Invariant(format!(
                    "orga group {name:?} collides with a stall name"
                )));
            }
        }

        let mut seen: HashMap<&str, &str> = HashMap::new();
        for g in &self.orga_groups {
            for c in &g.categories {
                if let Some(other) = seen.get(c.as_str()) {
                    return Err(ConfigError::Invariant(format!(
                        "category {c:?} is routed to multiple orga groups: \
                         {other:?} and {:?}",
                        g.name
                    )));
                }
                seen.insert(c, &g.name);
            }
        }

        Ok(())
    }

    /// Find the orga group responsible for `category`, or the configured
    /// default if no group claims it.
    pub fn route_category(&self, category: &str) -> &str {
        for g in &self.orga_groups {
            if g.categories.iter().any(|c| c == category) {
                return &g.name;
            }
        }
        // validate() guarantees exactly one default exists.
        self.orga_groups
            .iter()
            .find(|g| g.default)
            .map(|g| g.name.as_str())
            .expect("validated config has exactly one default")
    }

    pub fn visible_stall_names(&self) -> Vec<&str> {
        self.stalls
            .iter()
            .filter(|s| !s.hidden)
            .map(|s| s.name.as_str())
            .collect()
    }

    pub fn all_stall_names(&self) -> Vec<&str> {
        self.stalls.iter().map(|s| s.name.as_str()).collect()
    }

    pub fn stall(&self, name: &str) -> Option<&Stall> {
        self.stalls.iter().find(|s| s.name == name)
    }

    pub fn orga_names(&self) -> Vec<&str> {
        self.orga_groups.iter().map(|g| g.name.as_str()).collect()
    }

    pub fn is_orga(&self, name: &str) -> bool {
        self.orga_groups.iter().any(|g| g.name == name)
    }

    pub fn is_known_group(&self, name: &str) -> bool {
        self.stalls.iter().any(|s| s.name == name) || self.is_orga(name)
    }

    pub fn location_id_for_group(&self, group_name: &str) -> Option<i32> {
        let stall = self.stall(group_name)?;
        self.locations.get(&stall.location).copied()
    }

    /// Ticket-text display for the requesting group. Stands render as
    /// "location [type]"; orga members fall back to their own name.
    pub fn display_for(&self, group_name: &str) -> String {
        match self.stall(group_name) {
            Some(s) => s.display(),
            None => group_name.to_string(),
        }
    }
}
