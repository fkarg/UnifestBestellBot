//! Pre-built reply keyboards. Same shapes as `bot/keyboards.py` on the
//! Python side. The teloxide adapter renders these into real
//! `KeyboardMarkup` values at the wire.

use super::Keyboard;
use crate::config::AppConfig;
use crate::models::Registration;

pub fn initial() -> Keyboard {
    Keyboard::Reply(vec![vec!["/help".into(), "/register".into()]])
}

pub fn main() -> Keyboard {
    Keyboard::Reply(vec![
        vec!["/help".into(), "/status".into()],
        vec!["/request".into()],
    ])
}

pub fn orga() -> Keyboard {
    Keyboard::Reply(vec![
        vec!["/help".into(), "/help2".into()],
        vec!["/all".into(), "/tickets".into(), "/move".into()],
        vec!["/wip".into(), "/close".into()],
    ])
}

pub fn for_user(reg: Option<&Registration>, config: &AppConfig) -> Keyboard {
    match reg {
        None => initial(),
        Some(r) if config.is_orga(&r.group_name) => orga(),
        Some(_) => main(),
    }
}

// --- /request step keyboards --------------------------------------------

pub fn categories() -> Keyboard {
    Keyboard::Reply(vec![
        vec!["Becher".into(), "Geld".into(), "/cancel".into()],
        vec!["Bier".into(), "Cocktail".into(), "Sonstiges".into()],
        vec!["Helfer".into()],
    ])
}

pub fn money() -> Keyboard {
    Keyboard::Reply(vec![
        vec!["Geld Abholen".into(), "Wechselgeld".into()],
        vec!["Freitext".into(), "/cancel".into()],
    ])
}

pub fn money_change() -> Keyboard {
    Keyboard::Reply(vec![
        vec!["Scheine".into(), "Münzen".into()],
        vec!["/cancel".into()],
    ])
}

pub fn cups() -> Keyboard {
    Keyboard::Reply(vec![
        vec!["Dreckige Abholen".into(), "/cancel".into()],
        vec!["Shotbecher".into(), "Normale Becher".into()],
    ])
}

pub fn amount() -> Keyboard {
    Keyboard::Reply(vec![
        vec!["0".into(), "Freitext".into(), "/cancel".into()],
        vec!["~10".into(), "~20".into(), "~50".into()],
    ])
}

pub fn helper() -> Keyboard {
    Keyboard::Reply(vec![
        vec!["zu viele".into(), "zu wenige".into()],
        vec!["Helfer nicht da".into(), "Liste Schichten".into()],
    ])
}
