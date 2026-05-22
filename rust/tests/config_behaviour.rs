//! Behavioural tests for the AppConfig contract: loading, validation,
//! routing, and the display strings handlers depend on.

mod common;

use unifestbestellbot::config::AppConfig;

#[test]
fn routes_explicit_categories_to_their_orga() {
    let c = common::test_config();
    assert_eq!(c.route_category("Geld"), "Finanz");
    assert_eq!(c.route_category("Becher"), "BiMi");
    assert_eq!(c.route_category("Cocktail"), "BiMi");
    assert_eq!(c.route_category("Helfer"), "Helfen");
}

#[test]
fn routes_unknown_category_to_default() {
    let c = common::test_config();
    assert_eq!(c.route_category("Eis"), "Zentrale");
    assert_eq!(c.route_category("Sonstiges"), "Zentrale");
}

#[test]
fn visible_stall_names_excludes_hidden() {
    let c = common::test_config();
    let names = c.visible_stall_names();
    assert!(names.contains(&"Cocktailbar 1"));
    assert!(names.contains(&"Biertheke 1"));
    assert!(!names.contains(&"Tickets"));
}

#[test]
fn all_stall_names_includes_hidden() {
    let c = common::test_config();
    assert!(c.all_stall_names().contains(&"Tickets"));
}

#[test]
fn display_for_renders_location_and_type_in_brackets() {
    let c = common::test_config();
    assert_eq!(c.display_for("Cocktailbar 1"), "Innenhof [Cocktail]");
    assert_eq!(c.display_for("Biertheke 1"), "Außenbereich [Bier]");
}

#[test]
fn display_for_orga_falls_back_to_group_name() {
    let c = common::test_config();
    assert_eq!(c.display_for("Finanz"), "Finanz");
    assert_eq!(c.display_for("ghost"), "ghost");
}

#[test]
fn is_orga_distinguishes_orga_from_stall() {
    let c = common::test_config();
    assert!(c.is_orga("Finanz"));
    assert!(!c.is_orga("Cocktailbar 1"));
    assert!(!c.is_orga("unknown"));
}

#[test]
fn is_known_group_accepts_hidden_stalls() {
    let c = common::test_config();
    assert!(c.is_known_group("Cocktailbar 1"));
    assert!(c.is_known_group("Tickets")); // hidden but known
    assert!(c.is_known_group("Finanz"));
    assert!(!c.is_known_group("nope"));
}

#[test]
fn location_id_lookup_via_stall_location_mapping() {
    let c = common::test_config();
    assert_eq!(c.location_id_for_group("Cocktailbar 1"), Some(12));
    assert_eq!(c.location_id_for_group("Biertheke 1"), Some(15));
    // Eingang is not in `locations:`.
    assert_eq!(c.location_id_for_group("Tickets"), None);
    assert_eq!(c.location_id_for_group("ghost"), None);
}

#[test]
fn multiple_stalls_can_share_location_and_type() {
    let yaml = r#"
stalls:
  - name: "Cocktailbar 1"
    location: "Forum Süd"
    type: "Cocktail"
  - name: "Cocktailbar 2"
    location: "Forum Süd"
    type: "Cocktail"
orga_groups:
  - name: "Zentrale"
    categories: ["x"]
    default: true
"#;
    let c: AppConfig = serde_yaml::from_str(yaml).unwrap();
    c.validate().expect("two same-shape stalls are allowed");
    assert_eq!(c.stall("Cocktailbar 1").unwrap().display(), "Forum Süd [Cocktail]");
    assert_eq!(c.stall("Cocktailbar 2").unwrap().display(), "Forum Süd [Cocktail]");
}

#[test]
fn validation_rejects_no_default_orga() {
    let yaml = r#"
stalls: []
orga_groups:
  - name: "A"
    categories: ["x"]
  - name: "B"
    categories: ["y"]
"#;
    let c: AppConfig = serde_yaml::from_str(yaml).unwrap();
    let err = c.validate().unwrap_err().to_string();
    assert!(err.contains("default"), "got {err}");
}

#[test]
fn validation_rejects_two_defaults() {
    let yaml = r#"
stalls: []
orga_groups:
  - name: "A"
    categories: ["x"]
    default: true
  - name: "B"
    categories: ["y"]
    default: true
"#;
    let c: AppConfig = serde_yaml::from_str(yaml).unwrap();
    assert!(c.validate().unwrap_err().to_string().contains("default"));
}

#[test]
fn validation_rejects_duplicate_category_routing() {
    let yaml = r#"
stalls: []
orga_groups:
  - name: "A"
    categories: ["Geld"]
    default: true
  - name: "B"
    categories: ["Geld"]
"#;
    let c: AppConfig = serde_yaml::from_str(yaml).unwrap();
    assert!(
        c.validate()
            .unwrap_err()
            .to_string()
            .contains("routed to multiple")
    );
}

#[test]
fn validation_rejects_duplicate_orga_name() {
    let yaml = r#"
stalls: []
orga_groups:
  - name: "A"
    categories: ["x"]
    default: true
  - name: "A"
    categories: ["y"]
"#;
    let c: AppConfig = serde_yaml::from_str(yaml).unwrap();
    assert!(c.validate().unwrap_err().to_string().contains("duplicate"));
}

#[test]
fn validation_rejects_duplicate_stall_name() {
    let yaml = r#"
stalls:
  - name: "X"
    location: "L"
    type: "Bier"
  - name: "X"
    location: "M"
    type: "Cocktail"
orga_groups:
  - name: "Z"
    categories: ["x"]
    default: true
"#;
    let c: AppConfig = serde_yaml::from_str(yaml).unwrap();
    assert!(c.validate().unwrap_err().to_string().contains("duplicate"));
}

#[test]
fn validation_rejects_orga_name_colliding_with_stall() {
    let yaml = r#"
stalls:
  - name: "Finanz"
    location: "L"
    type: "Bier"
orga_groups:
  - name: "Finanz"
    categories: ["Geld"]
    default: true
"#;
    let c: AppConfig = serde_yaml::from_str(yaml).unwrap();
    assert!(c.validate().unwrap_err().to_string().contains("collides"));
}

#[test]
fn shift_digest_defaults_to_disabled() {
    let c = common::test_config();
    assert!(!c.shift_digest.enabled);
}

#[test]
fn shift_digest_parses_time_strings() {
    let yaml = r#"
stalls: []
orga_groups:
  - name: "Z"
    categories: ["x"]
    default: true
shift_digest:
  enabled: true
  window_start: "18:00:00"
  window_end: "02:30:00"
"#;
    let c: AppConfig = serde_yaml::from_str(yaml).unwrap();
    c.validate().unwrap();
    use chrono::Timelike;
    assert_eq!(c.shift_digest.window_start.hour(), 18);
    assert_eq!(c.shift_digest.window_end.hour(), 2);
    assert_eq!(c.shift_digest.window_end.minute(), 30);
}
