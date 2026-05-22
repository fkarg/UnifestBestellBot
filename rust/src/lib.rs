//! UnifestBestellBot — Rust port. The Python implementation in
//! `../src/unifestbestellbot/` is the behavioural reference; this
//! crate aims to be drop-in compatible at every contract boundary
//! (config.yaml schema, SQLite schema, SSE payload shape, German
//! user-facing strings, Engelsystem fixture).

pub mod config;
pub mod db;
pub mod engelsystem;
pub mod events;
pub mod i18n;
pub mod models;
pub mod repo;
pub mod settings;
pub mod web;
