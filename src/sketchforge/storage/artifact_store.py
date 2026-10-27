"""Artifact store: persist generated project files and benchmark artefacts."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path


class ArtifactStore:
    """Store generated project bundles, renders, and reports under a content-addressed tree."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def store(self, name: str, files: dict[str, str]) -> str:
        """Persist a dict of {relative_path: content} and return the bundle id."""
        bundle_id = _bundle_id(name, files)
        dest = self.root / bundle_id
        if dest.exists():
            return bundle_id  # already stored
        dest.mkdir(parents=True)
        for rel, content in files.items():
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        meta = {"name": name, "bundle_id": bundle_id, "files": len(files),
                "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        (dest / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return bundle_id

    def retrieve(self, bundle_id: str) -> dict[str, str] | None:
        dest = self.root / bundle_id
        if not dest.exists():
            return None
        return {
            p.relative_to(dest).as_posix(): p.read_text(encoding="utf-8")
            for p in dest.rglob("*")
            if p.is_file() and p.name != "_meta.json"
        }

    def list_bundles(self) -> list[dict]:
        result: list[dict] = []
        for meta_path in self.root.glob("*/_meta.json"):
            try:
                result.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return sorted(result, key=lambda m: m.get("stored_at", ""), reverse=True)


def _bundle_id(name: str, files: dict[str, str]) -> str:
    h = hashlib.sha256()
    h.update(name.encode())
    for k in sorted(files):
        h.update(k.encode())
        h.update(files[k].encode())
    return h.hexdigest()[:20]
