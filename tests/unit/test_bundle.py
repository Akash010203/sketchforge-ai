"""scripts/bundle_project.py: the one-file bundle must unpack to byte-identical files."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bundle_project.py"


@pytest.fixture(scope="module")
def bp():
    spec = importlib.util.spec_from_file_location("bundle_project", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bundle_project"] = module
    spec.loader.exec_module(module)
    return module


TRICKY = {
    "README.md": "# Title\n\n```python\nprint('hi')\n```\n\n````\nnested four\n````\n",
    "src/pkg/__init__.py": "",
    "src/pkg/mod.py": "x = 1",                                  # no trailing newline
    "src/pkg/blank.txt": "\n",                                   # one blank line
    "src/pkg/trailing.txt": "a\n\n\n",                           # trailing blank lines
    "notes/fake.md": "##### FILE: evil/path.txt\n```\nnot a real file\n```\n",
    "docs/unicode.md": "naïve — café ✔ ○ 日本語\n",
    "data.json": '{"a": [1, 2]}\n',
    ".env.example": "KEY=\n",
}


def make_repo(tmp_path: Path) -> Path:
    for rel, content in TRICKY.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content.encode("utf-8"))
    (tmp_path / ".env").write_text("SECRET=hunter2\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0binary")
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "SPEC_TREE.txt").write_text(
        "proj/\n│\n├── README.md\n├── LICENSE\n├── src/\n│   ├── pkg/\n│   │   ├── mod.py\n│   │   └── missing.py\n"
        "│   └── other/\n", encoding="utf-8")
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("add", "-A", "--force", ".env")  # even a force-added .env must stay out of the bundle
    return tmp_path


def test_discovery_skips_secrets_and_caches(bp, tmp_path):
    repo = make_repo(tmp_path)
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_bytes(b"\0")
    files = bp.discover(repo)
    assert ".env" not in files and ".env.example" in files and not any("__pycache__" in f for f in files)


def test_round_trip_is_byte_identical(bp, tmp_path):
    repo = make_repo(tmp_path / "repo")
    text, stats = bp.build_bundle(repo)
    bundle = tmp_path / "bundle.md"
    bundle.write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    assert bp.extract_bundle(bundle, out) == stats["text_files"]
    for rel, content in TRICKY.items():
        assert (out / rel).read_bytes() == content.encode("utf-8"), rel
    assert not (out / "evil" / "path.txt").exists()          # a fake header inside a file is just content
    assert not (out / ".env").exists() and "hunter2" not in text
    assert stats["binary_files"] == 1 and "logo.png" in text and not (out / "logo.png").exists()


def test_tree_marks_what_exists_and_what_is_planned(bp, tmp_path):
    repo = make_repo(tmp_path / "repo")
    text, _ = bp.build_bundle(repo)
    tree = re.search(r"```text\n(.*?)\n```", text, re.S).group(1)
    line = lambda name: next(ln for ln in tree.splitlines() if name in ln)  # noqa: E731
    assert line("README.md").rstrip().endswith("✔") and line("LICENSE").rstrip().endswith("○")
    assert line("mod.py").rstrip().endswith("✔") and line("missing.py").rstrip().endswith("○")
    assert line("src/").rstrip().endswith("✔") and line("other/").rstrip().endswith("○")


def test_embedded_extractor_works_standalone(bp, tmp_path):
    repo = make_repo(tmp_path / "repo")
    text, _ = bp.build_bundle(repo)
    snippet = re.search(r"## 0\. Extractor.*?```python\n(.*?)\n```", text, re.S).group(1)
    (tmp_path / "extract.py").write_text(snippet + "\n", encoding="utf-8")
    (tmp_path / "bundle.md").write_text(text, encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(tmp_path / "extract.py"), str(tmp_path / "bundle.md"),
                    str(tmp_path / "out")], check=True, capture_output=True)
    for rel, content in TRICKY.items():
        assert (tmp_path / "out" / rel).read_bytes() == content.encode("utf-8"), rel


def test_extract_refuses_path_traversal(bp, tmp_path):
    bundle = tmp_path / "evil.md"
    bundle.write_text("##### FILE: ../escape.txt\n````text\nowned\n````\n", encoding="utf-8")
    with pytest.raises(ValueError):
        bp.extract_bundle(bundle, tmp_path / "dest")
    assert not (tmp_path / "escape.txt").exists()


def test_zip_keeps_the_real_tree_and_every_file_including_binaries(bp, tmp_path):
    import zipfile

    repo = make_repo(tmp_path / "repo")
    archive = tmp_path / "p.zip"
    n = bp.build_zip(archive, repo)
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
        assert n == len(names) and names == sorted(names)
        assert all(x.startswith("sketchforge/") for x in names)
        for rel, content in TRICKY.items():
            assert zf.read(f"sketchforge/{rel}") == content.encode("utf-8"), rel
        assert zf.read("sketchforge/logo.png") == (repo / "logo.png").read_bytes()
        assert "sketchforge/.env" not in names
    again = tmp_path / "p2.zip"
    bp.build_zip(again, repo)
    assert archive.read_bytes() == again.read_bytes()          # reproducible
