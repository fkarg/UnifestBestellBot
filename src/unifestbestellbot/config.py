"""Year-specific configuration: which stalls exist, which orga groups handle
which request categories, and where each stall maps onto an Engelsystem
location id. Loaded once at startup, validated, then read-only."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, model_validator


class Stall(BaseModel):
    """A stand at the event. Identified by (location, type) — there is no
    separate team identity in the bot. Whichever crew is currently on shift
    `/register`s at this stand; multiple crews may cycle through the same
    stand over the event."""

    location: str  # physical area, e.g. "Forum Süd", "DJ", "Mitte"
    type: str  # what the stand sells / does, e.g. "Bier", "Cocktail", "Tickets"
    hidden: bool = False

    @property
    def name(self) -> str:
        """Stable identifier shown in the /register picker and stored as
        Registration.group_name. Volunteers see this exact string."""
        return f"{self.location} {self.type}"

    @property
    def display(self) -> str:
        """How the stand appears in ticket text to orga: location first
        (the thing they walk to), type in brackets (what they bring)."""
        return f"{self.location} [{self.type}]"


class OrgaGroup(BaseModel):
    name: str
    categories: list[str]
    default: bool = False


class AppConfig(BaseModel):
    stalls: list[Stall]
    orga_groups: list[OrgaGroup]
    locations: dict[str, int] = {}

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        defaults = [g for g in self.orga_groups if g.default]
        if len(defaults) != 1:
            raise ValueError(
                f"exactly one orga_group must be marked default; found {len(defaults)}"
            )

        orga_names = [g.name for g in self.orga_groups]
        if len(orga_names) != len(set(orga_names)):
            raise ValueError("orga_groups have duplicate names")

        stall_keys = [(s.location, s.type) for s in self.stalls]
        if len(stall_keys) != len(set(stall_keys)):
            raise ValueError("stalls have duplicate (location, type) pairs")

        # Orga names must not collide with stand identifiers — both live in
        # the same registration namespace.
        stall_names = {s.name for s in self.stalls}
        for name in orga_names:
            if name in stall_names:
                raise ValueError(
                    f"orga group {name!r} collides with a stand identifier"
                )

        seen: dict[str, str] = {}
        for g in self.orga_groups:
            for c in g.categories:
                if c in seen:
                    raise ValueError(
                        f"category {c!r} is routed to multiple orga groups: "
                        f"{seen[c]!r} and {g.name!r}"
                    )
                seen[c] = g.name

        return self

    def route_category(self, category: str) -> str:
        for g in self.orga_groups:
            if category in g.categories:
                return g.name
        return next(g.name for g in self.orga_groups if g.default)

    def visible_stall_names(self) -> list[str]:
        return [s.name for s in self.stalls if not s.hidden]

    def all_stall_names(self) -> list[str]:
        return [s.name for s in self.stalls]

    def stall(self, name: str) -> Stall | None:
        return next((s for s in self.stalls if s.name == name), None)

    def orga_names(self) -> list[str]:
        return [g.name for g in self.orga_groups]

    def is_orga(self, group_name: str | None) -> bool:
        return group_name is not None and group_name in self.orga_names()

    def is_known_group(self, group_name: str | None) -> bool:
        if group_name is None:
            return False
        return group_name in self.all_stall_names() or group_name in self.orga_names()

    def location_id_for_group(self, group_name: str) -> int | None:
        stall = self.stall(group_name)
        if stall is None:
            return None
        return self.locations.get(stall.location)

    def display_for(self, group_name: str) -> str:
        """What to show in ticket text for the requesting group: a stand's
        location+type, or the orga group's name verbatim if the requester is
        an orga member (rare but possible)."""
        stall = self.stall(group_name)
        return stall.display if stall is not None else group_name


def load_config(path: str | Path) -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(Path(path).read_text()))
