"""Year-specific configuration: which stalls exist, which orga groups handle
which request categories, and where each stall maps onto an Engelsystem
location id. Loaded once at startup, validated, then read-only."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, model_validator


class Stall(BaseModel):
    name: str
    location: str
    hidden: bool = False


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

        stall_names = [s.name for s in self.stalls]
        if len(stall_names) != len(set(stall_names)):
            raise ValueError("stalls have duplicate names")

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


def load_config(path: str | Path) -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(Path(path).read_text()))
