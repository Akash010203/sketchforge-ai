"""Load and chunk local Markdown, text, Python, and web documents."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

SUPPORTED = {".md", ".txt", ".rst", ".py", ".html", ".yaml", ".yml", ".json"}


@dataclass
class Document:
    id: str
    text: str
    source: str
    metadata: dict

    def to_dict(self):
        return asdict(self)


def _chunks(text: str, max_chars: int, overlap: int):
    paragraphs = re.split(r"\n\s*\n", text)
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}" if current else paragraph
            continue
        if current:
            yield current
        prefix = current[-overlap:] if overlap and current else ""
        current = (prefix + "\n" + paragraph).strip()
        while len(current) > max_chars:
            yield current[:max_chars]
            current = current[max_chars - overlap:]
    if current:
        yield current


def load_documents(paths, *, max_chars: int = 1800, overlap: int = 180) -> list[Document]:
    """Read files or directory trees, returning stable chunk IDs and file metadata."""
    if max_chars <= 0 or overlap < 0 or overlap >= max_chars:
        raise ValueError("Require max_chars > overlap >= 0")
    roots = [Path(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)]
    files = []
    for root in roots:
        files.extend([root] if root.is_file() else
                     [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED])
    docs = []
    for path in sorted(set(files)):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, chunk in enumerate(_chunks(text, max_chars, overlap)):
            doc_id = hashlib.sha256(f"{path.resolve()}:{i}:{chunk}".encode()).hexdigest()[:20]
            docs.append(Document(doc_id, chunk, str(path),
                                 {"extension": path.suffix.lower(), "chunk": i,
                                  "relative_name": path.name}))
    return docs
