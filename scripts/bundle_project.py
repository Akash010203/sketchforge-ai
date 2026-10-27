#!/usr/bin/env python
"""Pack the whole project into ONE readable text file, arranged as the specification's tree, and unpack it again.

    python scripts/bundle_project.py                       # -> output/SKETCHFORGE_PROJECT.md
    python scripts/bundle_project.py --out my_bundle.md
    python scripts/bundle_project.py --extract my_bundle.md --to restored/
    python scripts/bundle_project.py --zip                 # -> output/sketchforge.zip (real folder tree, binaries included)

The bundle has three parts: (1) the specification's tree (docs/SPEC_TREE.txt) with a mark on every
entry saying whether it exists yet, (2) the files that exist but are not in that tree, (3) every
text file, in tree order, each in its own fence. Binary files (the sample sketch PNGs) are listed
with size and SHA-256 and omitted; ``scripts/make_sample_sketches.py`` regenerates them.

Which files go in: everything git tracks plus untracked files that are not ignored, plus
``experiments/results/*.json`` (measured benchmark output, normally ignored). Secrets are never
included: ``.env`` files other than ``.env.example`` are skipped.

``--extract`` is also available as a standalone snippet at the top of every bundle, so a bundle can
be unpacked on a machine that has nothing but Python.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER_RE = re.compile(r"^##### FILE: (?P<path>\S.*?)(?P<flags>(?: \[[a-z ]+\])*)$")
FENCE_RE = re.compile(r"^(?P<fence>`{3,})(?P<lang>[\w+.-]*)$")
NO_NEWLINE = "[no trailing newline]"
LANG = {".py": "python", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".json": "json",
        ".txt": "text", ".gitignore": "gitignore", ".example": "dotenv", ".cfg": "ini", ".sh": "bash"}
ALWAYS_INCLUDE = ("experiments/results/*.json",)
NEVER = (re.compile(r"(^|/)\.env(\.(?!example$).*)?$"), re.compile(r"(^|/)(__pycache__|\.venv|\.git)(/|$)"),
         re.compile(r"\.(pyc|pyo|sqlite3?|pt|pth|ckpt|safetensors)$"))

EXTRACTOR = '''import re, sys, pathlib
src, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
lines = src.read_text(encoding="utf-8").split("\\n")
head = re.compile(r"^##### FILE: (\\S.*?)((?: \\[[a-z ]+\\])*)$")
i = n = 0
while i < len(lines):
    m = head.match(lines[i]); i += 1
    if not m:
        continue
    path, flags = m.group(1), m.group(2)
    fence = re.match(r"^(`{3,})[\\w+.-]*$", lines[i]).group(1); i += 1
    body = []
    while lines[i] != fence:
        body.append(lines[i]); i += 1
    i += 1
    text = "" if "[empty]" in flags else "\\n".join(body) + ("" if "[no trailing newline]" in flags else "\\n")
    target = (dest / path).resolve()
    assert str(target).startswith(str(dest.resolve())), path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8")); n += 1
print("extracted", n, "files to", dest)
'''


# --------------------------------------------------------------------------------------- discovery
def _git(root: Path, *args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def discover(root: Path = ROOT) -> list[str]:
    """Relative POSIX paths of every file that belongs in the bundle."""
    found = set(_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    for pattern in ALWAYS_INCLUDE:
        found.update(p.relative_to(root).as_posix() for p in root.glob(pattern))
    return sorted(p for p in found if (root / p).is_file() and not any(rx.search(p) for rx in NEVER))


def read_text(path: Path) -> str | None:
    """The file's text, or None if it is binary."""
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# --------------------------------------------------------------------------------------- spec tree
def parse_spec_tree(text: str) -> list[tuple[str, str, bool]]:
    """-> [(line, path, is_dir)] for every entry line of the tree (``path`` is '' for blank/spacer lines)."""
    rows: list[tuple[str, str, bool]] = []
    stack: list[str] = []
    for i, line in enumerate(text.splitlines()):
        if i == 0:
            rows.append((line, "", True))  # the root line, "sketchforge/"
            continue
        m = re.search(r"[├└]── ", line)
        if not m:
            rows.append((line, "", False))
            continue
        depth = m.start() // 4
        name = line[m.end():].split("#")[0].strip()
        is_dir = name.endswith("/")
        del stack[depth:]
        stack.append(name.rstrip("/"))
        rows.append((line, "/".join(stack), is_dir))
    return rows


def render_tree(rows: list[tuple[str, str, bool]], existing: set[str]) -> tuple[str, set[str]]:
    """The spec tree with a status mark per entry: ``✔`` exists, ``○`` not created yet."""
    dirs_present = {d for p in existing for d in _parents(p)}
    out, in_spec = [], set()
    width = max((len(line) for line, _, _ in rows), default=0) + 3
    for line, path, is_dir in rows:
        if not path:
            out.append(line)
            continue
        in_spec.add(path)
        ok = (path in dirs_present) if is_dir else (path in existing)
        out.append(f"{line.ljust(width)}{'✔' if ok else '○'}")
    return "\n".join(out), in_spec


def _parents(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[: i + 1]) for i in range(len(parts) - 1)]


# --------------------------------------------------------------------------------------- bundling
def fence_for(content: str) -> str:
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", content)), default=0)
    return "`" * max(4, longest + 1)


def build_bundle(root: Path = ROOT) -> tuple[str, dict]:
    files = discover(root)
    existing = set(files)
    spec_file = root / "docs" / "SPEC_TREE.txt"
    spec_text = spec_file.read_text(encoding="utf-8") if spec_file.is_file() else "sketchforge/\n"
    rows = parse_spec_tree(spec_text)
    tree, in_spec = render_tree(rows, existing)
    in_tree_order = [p for _, p, d in rows if p and not d and p in existing]
    additions = [p for p in files if p not in in_spec]
    order = in_tree_order + additions

    texts: dict[str, str] = {}
    binaries: list[tuple[str, int, str]] = []
    for p in order:
        content = read_text(root / p)
        if content is None:
            data = (root / p).read_bytes()
            binaries.append((p, len(data), hashlib.sha256(data).hexdigest()))
        else:
            texts[p] = content
    planned = [p for _, p, d in rows if p and not d and p not in existing]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.strip())

    out: list[str] = []
    out.append("# SketchForge — complete project in one file\n")
    out.append(f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} from commit `{commit or 'n/a'}`"
               f"{' plus uncommitted changes' if dirty else ''} by `scripts/bundle_project.py`.\n")
    out.append(f"- **{len(texts)} text files** are included below, in the order of the tree.")
    out.append(f"- **{len(binaries)} binary files** are listed but not embedded (`scripts/make_sample_sketches.py` recreates the sample sketches).")
    out.append(f"- **{len(planned)} files in the specification's tree do not exist yet** (marked ○). They belong to later "
               "phases; nothing is faked to fill them, see `TASKS.md` for status.")
    out.append(f"- **{len(additions)} files exist that the tree does not list** (marked in section 2); the reasons are in `docs/FILE_STRUCTURE.md`.\n")
    out.append("To unpack on any machine with Python (writes every file under `restored/`):\n")
    out.append("```bash\npython extract.py SKETCHFORGE_PROJECT.md restored/\n```\n")
    out.append("where `extract.py` is the snippet in section 0.\n")
    out.append("## 0. Extractor (save as `extract.py`)\n")
    out.append("```python\n" + EXTRACTOR.rstrip("\n") + "\n```\n")
    out.append("## 1. Project tree (✔ exists · ○ planned, not created yet)\n")
    out.append("```text\n" + tree + "\n```\n")
    out.append("## 2. Files that exist but are not in the specification's tree\n")
    out.append("\n".join(f"- `{p}`" for p in additions) if additions else "(none)")
    out.append("")
    if binaries:
        out.append("\n### Binary files (not embedded)\n")
        out.append("| file | bytes | sha256 |\n|---|---:|---|")
        out.extend(f"| `{p}` | {n} | `{h[:16]}…` |" for p, n, h in binaries)
        out.append("")
    out.append("## 3. File contents\n")
    for p in order:
        if p not in texts:
            continue
        content = texts[p]
        flags = " [empty]" if content == "" else ("" if content.endswith("\n") else f" {NO_NEWLINE}")
        body = content[:-1] if content.endswith("\n") else content
        fence = fence_for(content)
        suffix = Path(p).suffix or Path(p).name
        lang = LANG.get(suffix, LANG.get(Path(p).name, ""))
        if p in additions:
            flags += " [not in spec tree]"
        out.append(f"##### FILE: {p}{flags}")
        out.append(f"{fence}{lang}")
        if content != "":
            out.append(body)
        out.append(fence)
        out.append("")
    stats = {"text_files": len(texts), "binary_files": len(binaries), "planned_missing": len(planned),
             "additions": len(additions), "commit": commit, "dirty": dirty}
    return "\n".join(out) + "\n", stats


# --------------------------------------------------------------------------------------- extraction
def extract_bundle(bundle: Path, dest: Path) -> int:
    lines = bundle.read_text(encoding="utf-8").split("\n")
    i = count = 0
    while i < len(lines):
        m = HEADER_RE.match(lines[i])
        i += 1
        if not m:
            continue
        path, flags = m.group("path"), m.group("flags")
        fence = FENCE_RE.match(lines[i])
        if fence is None:
            raise ValueError(f"{path}: no fence after the header")
        i += 1
        body: list[str] = []
        while lines[i] != fence.group("fence"):
            body.append(lines[i])
            i += 1
        i += 1
        text = "" if "[empty]" in flags else "\n".join(body) + ("" if NO_NEWLINE in flags else "\n")
        target = (dest / path).resolve()
        if not str(target).startswith(str(dest.resolve())):
            raise ValueError(f"refusing to write outside the destination: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
        count += 1
    return count


def build_zip(out: Path, root: Path = ROOT, top: str = "sketchforge") -> int:
    """Write every bundled file (binaries included) into a zip under a single ``top/`` folder, keeping the
    real directory tree. Entries are sorted and timestamped identically, so the archive is reproducible."""
    files = discover(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            info = zipfile.ZipInfo(f"{top}/{rel}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if rel.startswith("scripts/") else 0o644) << 16
            zf.writestr(info, (root / rel).read_bytes())
    return len(files)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "output" / "SKETCHFORGE_PROJECT.md"))
    ap.add_argument("--extract", metavar="BUNDLE", help="unpack a bundle instead of creating one")
    ap.add_argument("--to", default="restored", help="destination directory for --extract")
    ap.add_argument("--zip", nargs="?", const=str(ROOT / "output" / "sketchforge.zip"), metavar="FILE",
                    help="write a zip of the real folder tree instead of the one-file bundle")
    args = ap.parse_args()
    if args.zip:
        n = build_zip(Path(args.zip))
        print(f"wrote {args.zip} ({Path(args.zip).stat().st_size / 1024:.0f} KiB, {n} files)")
        return 0
    if args.extract:
        n = extract_bundle(Path(args.extract), Path(args.to))
        print(f"extracted {n} files to {args.to}")
        return 0
    text, stats = build_bundle()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text.encode('utf-8')) / 1024:.0f} KiB): {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
