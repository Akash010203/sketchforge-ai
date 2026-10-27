"""Version control: thin wrapper for tracking DesignDocument revisions in memory + JSON snapshots."""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Revision:
    index: int
    label: str
    snapshot: dict
    author: str = "user"
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class VersionControl:
    """Lightweight revision history for DesignDocuments and generated files.

    Stores a linear history of snapshots.  Can undo, redo, and branch (fork).
    All revisions are serialisable to JSON for persistence.
    """

    def __init__(self, max_revisions: int = 50):
        self._history: list[Revision] = []
        self._cursor: int = -1
        self._max = max_revisions

    def commit(self, label: str, snapshot: Any, author: str = "user") -> Revision:
        """Append a new revision, dropping forward history if cursor is not at head."""
        # Drop any redo history
        if self._cursor < len(self._history) - 1:
            self._history = self._history[: self._cursor + 1]

        idx = len(self._history)
        rev = Revision(index=idx, label=label, snapshot=copy.deepcopy(snapshot), author=author)
        self._history.append(rev)

        # Prune oldest if over limit
        if len(self._history) > self._max:
            self._history.pop(0)
            for i, r in enumerate(self._history):
                r.index = i

        self._cursor = len(self._history) - 1
        return rev

    def undo(self) -> Revision | None:
        if self._cursor <= 0:
            return None
        self._cursor -= 1
        return self._history[self._cursor]

    def redo(self) -> Revision | None:
        if self._cursor >= len(self._history) - 1:
            return None
        self._cursor += 1
        return self._history[self._cursor]

    def current(self) -> Revision | None:
        if not self._history:
            return None
        return self._history[self._cursor]

    def log(self) -> list[dict]:
        return [
            {"index": r.index, "label": r.label, "author": r.author, "timestamp": r.timestamp}
            for r in self._history
        ]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"cursor": self._cursor, "history": [
            {"index": r.index, "label": r.label, "author": r.author,
             "timestamp": r.timestamp, "snapshot": r.snapshot}
            for r in self._history
        ]}
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "VersionControl":
        vc = cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        vc._history = [
            Revision(**{k: v for k, v in r.items()})
            for r in data.get("history", [])
        ]
        vc._cursor = data.get("cursor", len(vc._history) - 1)
        return vc
