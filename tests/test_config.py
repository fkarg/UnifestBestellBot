import pytest
import yaml

from unifestbestellbot.config import AppConfig, load_config


def test_route_category_matches_explicit_orga(config):
    assert config.route_category("Geld") == "Finanz"
    assert config.route_category("Becher") == "BiMi"
    assert config.route_category("Cocktail") == "BiMi"
    assert config.route_category("Helfer") == "Helfen"


def test_route_category_falls_back_to_default(config):
    assert config.route_category("Eis") == "Zentrale"
    assert config.route_category("Sonstiges") == "Zentrale"


def test_visible_stalls_excludes_hidden(config):
    names = config.visible_stall_names()
    assert "Cocktailbar" in names
    assert "Biertheke 1" in names
    assert "Tickets" not in names


def test_all_stalls_includes_hidden(config):
    assert "Tickets" in config.all_stall_names()


def test_stall_lookup(config):
    s = config.stall("Cocktailbar")
    assert s is not None
    assert s.location == "Innenhof"
    assert config.stall("missing") is None


def test_is_orga(config):
    assert config.is_orga("Finanz")
    assert not config.is_orga("Cocktailbar")
    assert not config.is_orga(None)
    assert not config.is_orga("unknown")


def test_is_known_group(config):
    assert config.is_known_group("Cocktailbar")
    assert config.is_known_group("Tickets")  # hidden but still known
    assert config.is_known_group("Finanz")
    assert not config.is_known_group("nope")
    assert not config.is_known_group(None)


def test_location_id_for_group(config):
    assert config.location_id_for_group("Cocktailbar") == 12
    assert config.location_id_for_group("Biertheke 1") == 15
    # Eingang has no engelsystem id configured
    assert config.location_id_for_group("Tickets") is None
    # Non-existent stall
    assert config.location_id_for_group("ghost") is None


def test_orga_names(config):
    assert set(config.orga_names()) == {"Finanz", "BiMi", "Helfen", "Zentrale"}


def test_at_least_one_default_required():
    with pytest.raises(ValueError, match="default"):
        AppConfig.model_validate(
            {
                "stalls": [],
                "orga_groups": [
                    {"name": "A", "categories": ["x"]},
                    {"name": "B", "categories": ["y"]},
                ],
            }
        )


def test_multiple_defaults_rejected():
    with pytest.raises(ValueError, match="default"):
        AppConfig.model_validate(
            {
                "stalls": [],
                "orga_groups": [
                    {"name": "A", "categories": ["x"], "default": True},
                    {"name": "B", "categories": ["y"], "default": True},
                ],
            }
        )


def test_duplicate_category_rejected():
    with pytest.raises(ValueError, match="routed to multiple"):
        AppConfig.model_validate(
            {
                "stalls": [],
                "orga_groups": [
                    {"name": "A", "categories": ["Geld"], "default": True},
                    {"name": "B", "categories": ["Geld"]},
                ],
            }
        )


def test_duplicate_orga_name_rejected():
    with pytest.raises(ValueError, match="duplicate names"):
        AppConfig.model_validate(
            {
                "stalls": [],
                "orga_groups": [
                    {"name": "A", "categories": ["x"], "default": True},
                    {"name": "A", "categories": ["y"]},
                ],
            }
        )


def test_duplicate_stall_name_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        AppConfig.model_validate(
            {
                "stalls": [
                    {"name": "X", "location": "L1"},
                    {"name": "X", "location": "L2"},
                ],
                "orga_groups": [
                    {"name": "A", "categories": ["x"], "default": True},
                ],
            }
        )


def test_load_config_from_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        yaml.dump(
            {
                "stalls": [{"name": "X", "location": "L"}],
                "orga_groups": [
                    {"name": "Z", "categories": ["any"], "default": True},
                ],
            }
        )
    )
    cfg = load_config(p)
    assert cfg.stalls[0].name == "X"
    assert cfg.route_category("any") == "Z"
    assert cfg.route_category("not-listed") == "Z"


def test_example_config_yaml_loads():
    """The committed example file must always be a valid config."""
    cfg = load_config("config.yaml.example")
    assert cfg.route_category("Geld") == "Finanz"
    assert "Cocktailbar" in cfg.visible_stall_names()
