#!/usr/bin/env python
"""Full synchronization of ALL modules, code, tests, and assets to sketchforge-ai.

Preserves the user's updated README.md, HACKATHON_FEEDBACK.md, and TAVILY_INTEGRATION.md,
while bringing over everything else:
- src/sketchforge (training, retrieval, datasets, cloud, domain, rendering, execution, repair, editor, etc.)
- tests/ (all unit, integration, e2e, evaluation)
- scripts/ (all scripts)
- assets/ (all diagrams, SVGs, sample sketches)
- config/
- checkpoints/
- experiments/
- deploy/ (both AWS and deploy/nebius)
- docs/ (all technical docs + hackathon docs)
"""

import os
import shutil
from pathlib import Path

SOURCE = Path(r"c:\Users\akash\Downloads\sketchforge")
TARGET = Path(r"c:\Users\akash\Downloads\sketchforge-ai")

# 1. Preserve user-edited files
saved_files = {}
for rel in ["README.md", "docs/HACKATHON_FEEDBACK.md", "docs/TAVILY_INTEGRATION.md"]:
    p = TARGET / rel
    if p.exists():
        saved_files[rel] = p.read_text(encoding="utf-8")
        print(f"Saved user edits for {rel}")

IGNORE_PATTERNS = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache", "*.zip", ".git"
)

# 2. Copy src/sketchforge submodules
src_source = SOURCE / "src" / "sketchforge"
src_target = TARGET / "src" / "sketchforge"
src_target.mkdir(parents=True, exist_ok=True)

for item in src_source.iterdir():
    if item.name.startswith((".", "__pycache__")):
        continue
    dest = src_target / item.name
    if item.is_dir():
        shutil.copytree(item, dest, dirs_exist_ok=True, ignore=IGNORE_PATTERNS)
    else:
        shutil.copy2(item, dest)
print("Synced all src/sketchforge submodules (training, retrieval, datasets, cloud, etc.)")

# 3. Copy top-level folders
for folder in ["tests", "scripts", "assets", "config", "checkpoints", "experiments", "deploy", "docs"]:
    s = SOURCE / folder
    d = TARGET / folder
    if s.exists():
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True, ignore=IGNORE_PATTERNS)
        else:
            shutil.copy2(s, d)
        print(f"Synced {folder}/")

# 4. Restore user-edited files
for rel, content in saved_files.items():
    p = TARGET / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"Restored user edits for {rel}")

print("\nFull sync complete! All files, training, retrieval, editor, and tests are present.")
