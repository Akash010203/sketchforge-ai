"""Schema versioning and migrations.

A migration is a pure function ``dict -> dict`` that upgrades a serialized document from one
schema version to the next. ``Migrator.migrate`` walks the chain until it reaches the target
version. Documents newer than the application are rejected rather than guessed at.

Only the current version (1.0.0) exists today, so the shipped chain is empty; the mechanism is
exercised by the unit tests with a throw-away chain.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from sketchforge.constants import SCHEMA_VERSION
from sketchforge.exceptions import MigrationError

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]


def parse_version(text: str) -> tuple[int, int, int]:
    try:
        major, minor, patch = (int(p) for p in text.split("."))
    except (ValueError, AttributeError) as exc:
        raise MigrationError(f"invalid schema version {text!r}; expected MAJOR.MINOR.PATCH") from exc
    return major, minor, patch


class Migrator:
    def __init__(self, target: str = SCHEMA_VERSION) -> None:
        parse_version(target)
        self.target = target
        self._steps: dict[str, tuple[str, MigrationFn]] = {}

    def register(self, from_version: str, to_version: str) -> Callable[[MigrationFn], MigrationFn]:
        parse_version(from_version)
        if parse_version(to_version) <= parse_version(from_version):
            raise MigrationError("a migration must move to a strictly newer version")

        def decorator(fn: MigrationFn) -> MigrationFn:
            if from_version in self._steps:
                raise MigrationError(f"a migration from {from_version} is already registered")
            self._steps[from_version] = (to_version, fn)
            return fn

        return decorator

    def migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise MigrationError("document must be a JSON object")
        version = data.get("schema_version")
        if not isinstance(version, str):
            raise MigrationError("document has no 'schema_version'")
        if parse_version(version) > parse_version(self.target):
            raise MigrationError(
                f"document uses schema {version}, newer than supported {self.target}; "
                "update SketchForge to open it"
            )
        current = copy.deepcopy(data)
        hops = 0
        while current["schema_version"] != self.target:
            step = self._steps.get(current["schema_version"])
            if step is None:
                raise MigrationError(
                    f"no migration path from schema {current['schema_version']} to {self.target}"
                )
            to_version, fn = step
            current = fn(current)
            current["schema_version"] = to_version
            hops += 1
            if hops > 100:
                raise MigrationError("migration chain does not terminate")
        return current


default_migrator = Migrator()


def migrate_to_current(data: dict[str, Any]) -> dict[str, Any]:
    return default_migrator.migrate(data)
