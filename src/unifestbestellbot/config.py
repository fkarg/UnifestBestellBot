"""Year-specific configuration: which stalls exist, which orga groups handle
which request categories, and where each stall maps onto an Engelsystem
location id. Loaded once at startup, validated, then read-only."""

from datetime import time
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, model_validator


class Stall(BaseModel):
    """A group registered to a stand at the event.

    - `name` is the group identity volunteers /register as (e.g.
      "Cocktailbar 1", "Biertheke Süd"). Stable across the event.
    - `location` is the physical area the group works at (e.g.
      "Forum Süd", "DJ", "Mitte").
    - `type` is what the stand does (e.g. "Bier", "Cocktail",
      "Tickets") — what BiMi needs to know to bring the right supplies.

    Multiple groups can share the same `(location, type)` — e.g.
    "Cocktailbar 1" and "Cocktailbar 2" both at Forum Süd. Volunteers
    pick their group by name; ticket text shown to orga is
    `"{location} [{type}]"`, so handlers orient on the stand, not on
    whichever crew is currently on shift."""

    name: str
    location: str
    type: str
    hidden: bool = False

    @property
    def display(self) -> str:
        """How the stand appears in ticket text to orga."""
        return f"{self.location} [{self.type}]"


class OrgaGroup(BaseModel):
    name: str
    categories: list[str]
    default: bool = False


class ShiftDigest(BaseModel):
    """Configuration for the periodic Engelsystem shift-start digest.

    When enabled, a background task wakes every `check_interval_minutes`,
    queries Engelsystem for upcoming shifts at every configured location,
    and DMs the orga group that handles the `Helfer` category with the
    rota of any shift starting within `lookahead_minutes`.

    Active only within the operational window (`window_start` to
    `window_end`, expressed in the bot's local timezone). The window may
    cross midnight — `window_start=18:00`, `window_end=02:00` is treated
    as "from 18:00 today through 02:00 tomorrow"."""

    enabled: bool = False
    window_start: time = time(0, 0)
    window_end: time = time(0, 0)  # equal start==end = always-on within
    check_interval_minutes: int = 5
    lookahead_minutes: int = 10


class AppConfig(BaseModel):
    stalls: list[Stall]
    orga_groups: list[OrgaGroup]
    locations: dict[str, int] = {}
    shift_digest: ShiftDigest = ShiftDigest()

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

        stall_names_list = [s.name for s in self.stalls]
        if len(stall_names_list) != len(set(stall_names_list)):
            raise ValueError("stalls have duplicate names")

        # Orga and stall names share the registration namespace.
        stall_names = set(stall_names_list)
        for name in orga_names:
            if name in stall_names:
                raise ValueError(
                    f"orga group {name!r} collides with a stall name"
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

    def resolve_group(self, query: str) -> str | None:
        """Case-insensitively resolve a free-text group reference to its
        canonical name (any stall or orga group), or None if unknown."""
        for name in self.all_stall_names() + self.orga_names():
            if name.casefold() == query.casefold():
                return name
        return None

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
