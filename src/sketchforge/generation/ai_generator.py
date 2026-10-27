"""AI-driven project file generator — Two-Stage Generation Pipeline.

Stage 1 (Plan & Architecture): Sends a lean prompt to nvidia/Nemotron-3_5-Lightning
  requesting only the AppSpec JSON (~500 tokens).  The AppSpec captures app name,
  pages, entities, field definitions, and route definitions.

Stage 2 (File Generation): Using the confirmed AppSpec, prompts the model to generate
  each dynamic file (frontend/home.js, backend/logic.py, backend/schema.sql, …)
  individually with a bounded 2,048-token cap per request, then merges all files into
  the project folder.

On any failure the pipeline falls back transparently to the template generator so the
UI always gets a usable project.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model selection: candidate priority order
# ---------------------------------------------------------------------------

# Pinned active model: nvidia/Nemotron-3_5-Lightning for reliable latency and adherence
_PINNED_MODEL = "nvidia/Nemotron-3_5-Lightning"
_NEMOTRON_MODEL = _PINNED_MODEL
_FALLBACK_MODELS = (
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
)


def _ts() -> str:
    """Return a compact HH:MM:SS timestamp string for progress messages."""
    return _dt.datetime.now().strftime("%H:%M:%S")


def _select_active_model(
    client,
    emit,
    *,
    ping_max_tokens: int = 64,
) -> tuple[str | None, str | None]:
    """Verify availability of the pinned Nemotron-3_5-Lightning model.

    Emits transparent, timestamped progress. If the pinned model fails,
    tries candidate fallbacks without rapid flapping or oscillation.
    """
    from sketchforge.integrations.provider_interface import ChatMessage, CompletionRequest

    models_to_try = (_PINNED_MODEL, *_FALLBACK_MODELS)
    last_err: str | None = None

    for idx, model in enumerate(models_to_try, start=1):
        short = model.split("/")[-1]
        is_pinned = (model == _PINNED_MODEL)
        emit(f"[{_ts()}] Stage 1 — {'connecting to pinned model' if is_pinned else 'trying fallback model'}: {short}…")
        ping = CompletionRequest(
            messages=(
                ChatMessage(role="user", content="ping"),
            ),
            purpose="studio_ping",
            max_tokens=ping_max_tokens,
            temperature=0.0,
            model=model,
        )
        try:
            client.complete(ping)
            emit(f"[{_ts()}] Stage 1 — model ready: {short}")
            return model, None
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            log.warning("Model probe failed for %s — %s", model, exc)
            emit(
                f"[{_ts()}] Stage 1 — {short} unavailable ({type(exc).__name__}: {exc}); "
                f"{'trying next fallback…' if idx < len(models_to_try) else 'no more candidates.'}"
            )
    return None, last_err

# ---------------------------------------------------------------------------
# Stage-1 prompt: AppSpec plan
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = """\
You are SketchForge Studio's architecture planner.
Given a short product brief, produce ONLY a compact JSON AppSpec.

Return ONLY a JSON object — no markdown fences, no explanation:
{
  "name": "<short app name>",
  "pages": [
    {"name": "<page_slug>", "title": "<Page Title>", "route": "/<slug>"}
  ],
  "entities": [
    {
      "name": "<EntityName>",
      "fields": [
        {"name": "<field>", "type": "<text|int|bool|float|date>"}
      ]
    }
  ],
  "include_backend": true
}

Rules:
- Keep the JSON under 500 tokens.
- At minimum include a "home" page and one entity if a backend is requested.
- The response MUST be valid JSON parseable by Python's json.loads.

Sketch layout rules (apply when the brief contains a <SketchDesignDocument> block):
- The block contains a "layout_block" sub-object with:
    "canvas"     — design canvas size in design pixels.
    "app_spec"   — a heuristic AppSpec already derived from the sketch.
    "components" — a flat list with id, type, parent_id, bbox_design_px (x/y/w/h),
                   label text, and confidence for every detected component.
    "hierarchy"  — a human-readable indented tree of component nesting.
- Use the "app_spec.pages" array to determine the page structure.
  Confirm and enrich the page names, titles, and routes.
- Use the "app_spec.entities" array for entity and field names.
- Use component types to infer the UI:
    "button" → ActionSpec (action=submit_form if inputs present, else navigate)
    "input"  → FieldSpec with the component's label text if present.
    "header" / "footer" / "sidebar" → structural layout containers (not entities).
    "card"   → repeating list item or data panel.
    "image"  → media content section.
- The RETURNED JSON "pages" must reflect the number of distinct top-level
  regions/flows detected (not arbitrarily invent new pages).
- If the layout_block is missing or empty, fall back to inferring from
  the legacy "regions" array (x/y/w/h in % of canvas).
"""

_PLAN_USER = """\
Product brief: {brief}
Include backend: {backend}

Generate the AppSpec plan now.
"""

# ---------------------------------------------------------------------------
# Stage-2 prompt: individual file generation
# ---------------------------------------------------------------------------

_FILE_SYSTEM = """\
You are SketchForge Studio's code generator.
Generate exactly ONE file based on the AppSpec and the file path given below.

Return the file content inside a single markdown code fence — NO JSON envelope, no extra explanation:

```<lang>
<full file content here>
```

Use the correct language tag (e.g. python, html, css, js, sql, text).

Rules:
- Use dark, modern aesthetics (background #111116, accent #d9ff5f, font Segoe UI).
- Generated HTML must be responsive (mobile-first).
- The Flask backend must bind to 0.0.0.0 and accept --port argument; add CORS header.
- CRITICAL: The API route is derived from the FIRST entity in the AppSpec.
  Derive it as: route = entity.name.lower().replace(' ', '_') + 's'
  Example: entity 'Task' → route 'tasks' → endpoint '/api/tasks'.
  Frontend JS must POST to /api/<route> and GET from /api/<route>.
  The Flask backend must expose /api/<route>, /api/<route>/<id> for GET/POST/PUT/DELETE.
  Use the SAME route in BOTH the frontend JS files AND the backend api.py.
  NEVER use '/api/submissions' unless the entity is literally named 'Submission'.
- Do NOT reference external CDN assets; all CSS/JS must be inline or in local files.
- Include a /api/health GET route in the Flask backend.
- Output ONLY the code fence — do not wrap it in JSON or add any other text.
"""

_FILE_USER = """\
AppSpec:
{spec}

Generate this file now:
Path: {path}
Description: {description}
"""

# ---------------------------------------------------------------------------
# File manifest derived from AppSpec
# ---------------------------------------------------------------------------

_STATIC_FILES = [
    ("index.html", "Root redirect page (meta-refresh to home.html)"),
    ("css/style.css", "Dark-themed responsive stylesheet (bg #111116, accent #d9ff5f)"),
]

_FRONTEND_FILES = [
    ("home.html", "Main landing page using the app name and entities from the AppSpec"),
    ("projects.html", "List page that GETs /api/<entity_route> (derived from AppSpec entity name) and renders items"),
    ("js/home.js", "Form submission logic — POSTs to /api/<entity_route> derived from the AppSpec first entity name"),
    ("js/projects.js", "Fetch and render records from GET /api/<entity_route> derived from the AppSpec first entity name"),
]

_BACKEND_FILES = [
    ("backend/schema.sql", "SQLite CREATE TABLE statements for every entity (use entity name as table name)"),
    ("backend/models.py", "Python dataclass models for every entity"),
    ("backend/database.py", "SQLite connection helper with schema init on first run"),
    ("backend/logic.py", "Business logic functions (CRUD) for every entity using the entity table name"),
    ("backend/api.py", "Flask CRUD REST API: routes /api/<entity_route> and /api/<entity_route>/<id> for CRUD; /api/health for readiness; bound to 0.0.0.0 with --port arg and CORS"),
    ("requirements.txt", "Flask>=3.0 and any other needed packages, one per line"),
]


def _file_manifest(spec: dict) -> list[tuple[str, str]]:
    """Return (path, description) tuples for every file to generate."""
    files = list(_STATIC_FILES) + list(_FRONTEND_FILES)
    if spec.get("include_backend", True):
        files += list(_BACKEND_FILES)
    return files


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_fallback_file_content(path_hint: str, spec: dict) -> str:
    """Produce deterministic, working fallback content for an individual file.

    Guarantees that if Nemotron fails on an individual file, the file is populated
    from the verified template generator and the project remains 100% intact.
    """
    from html import escape
    from sketchforge.generation.studio_generator import _studio_css, _home_js, _projects_js

    name = spec.get("name") or "New App"
    safe_name = escape(name)
    pages = spec.get("pages") or [{"name": "home", "title": name, "route": "/"}]
    entities = spec.get("entities") or []

    main_entity_name = entities[0].get("name", "Submission") if entities else "Submission"
    main_entity_fields = entities[0].get("fields", []) if entities else [
        {"name": "title", "type": "text"},
        {"name": "details", "type": "text"},
    ]
    route = re.sub(r"[^a-z0-9]+", "-", main_entity_name.lower()).strip("-") + "s"
    storage_key = f"sketchforge-{route}"

    if path_hint == "index.html":
        return (
            '<!doctype html><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0; url=home.html">'
            f'<title>{safe_name}</title><a href="home.html">Open {safe_name}</a>'
        )

    if path_hint == "css/style.css":
        return _studio_css()

    if path_hint == "requirements.txt":
        return "Flask>=3.0\nWerkzeug>=3.0\n"

    if path_hint == "home.html":
        inputs = []
        for f in main_entity_fields:
            fname = escape(f.get("name", "title"))
            flabel = escape(fname.replace("_", " ").title())
            inputs.append(f'<label>{flabel}<input name="{fname}" required placeholder="Enter {flabel}"></label>')
        form_html = (
            f'<form id="idea-form">{"".join(inputs)}'
            f'<button class="primary" type="submit">Submit {escape(main_entity_name)} <span>↗</span></button>'
            '<p class="form-note" id="form-note">Records save directly to local workspace database.</p></form>'
        )
        nav_html = "".join(f'<a href="{p.get("name", "home")}.html">{escape(p.get("title", p.get("name", "").title()))}</a>' for p in pages)
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_name} · Home</title><link rel="stylesheet" href="css/style.css"></head>
<body><header class="top"><a class="brand" href="home.html"><span class="brand-mark">s</span>{safe_name}</a><nav>{nav_html}</nav><button class="avatar" aria-label="Account">A</button></header>
<main><div class="eyebrow"><span class="spark">✳</span> SKETCHFORGE HYBRID GENERATION</div>
<section class="hero"><div class="hero-copy"><p class="kicker">Verified local runtime</p><h1>{safe_name}<br><em>ready to run.</em></h1>
<p class="lede">Full-stack web application with SQLite database and REST API.</p></div>
<aside class="welcome-card"><div class="card-top"><span class="card-icon">✳</span><span class="live-pill"><i></i> LIVE RUNTIME</span></div><div class="orb orb-one"></div><div class="orb orb-two"></div><div class="card-art"><div class="art-window"><div class="art-nav"><b></b><span></span><span></span><span></span></div><div class="art-lines"><i></i><i></i><i></i></div><div class="art-blocks"><b></b><b></b><b></b></div></div><span class="float-chip">✦ &nbsp; connected to backend</span></div><div class="card-foot"><span>DATABASE ACTIVE</span><span>PORT REST</span></div></aside></section>
<section class="work"><div class="work-heading"><div><span class="kicker">DATA ENTRY</span><h2>Add New {escape(main_entity_name)}</h2></div><span class="counter">01 <i>/</i> 02</span></div>
<div class="builder"><div class="builder-head"><div class="builder-label"><span class="status-dot"></span><b>Enter details below</b></div><span class="private">⌁ &nbsp; Local SQLite</span></div>
{form_html}</div></section>
<footer><span>✳ &nbsp;SketchForge Studio</span><span>Autonomous full-stack runtime&nbsp; ↗</span></footer></main><script src="js/home.js"></script></body></html>'''

    if path_hint == "projects.html":
        nav_html = "".join(f'<a href="{p.get("name", "home")}.html">{escape(p.get("title", p.get("name", "").title()))}</a>' for p in pages)
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_name} · Records</title><link rel="stylesheet" href="css/style.css"></head>
<body><header class="top"><a class="brand" href="home.html"><span class="brand-mark">s</span>{safe_name}</a><nav>{nav_html}</nav><button class="avatar" aria-label="Account">A</button></header>
<main><div class="eyebrow"><span class="spark">✳</span> SAVED RECORDS</div>
<section class="hero"><div class="hero-copy"><p class="kicker">Data Explorer</p><h1>Saved {escape(main_entity_name)}s<br><em>in local database.</em></h1>
<p class="lede">Live queries against the isolated SQLite backend.</p></div></section>
<section class="work"><div class="work-heading"><div><span class="kicker">WORKSPACE DATA</span><h2>Submissions Explorer</h2></div></div>
<div class="builder"><ul id="submissions-list" class="submission-list"></ul></div></section>
<footer><span>✳ &nbsp;SketchForge Studio</span><span><a href="home.html" style="color:inherit">Add more records ↗</a></span></footer></main><script src="js/projects.js"></script></body></html>'''

    if path_hint == "js/home.js":
        from sketchforge.generation.app_specification import EntitySpec, FieldSpec
        entity_obj = EntitySpec(
            main_entity_name,
            [FieldSpec(f.get("name", "title"), f.get("name", "Title")) for f in main_entity_fields],
        )
        return _home_js(entity_obj, route, storage_key)

    if path_hint == "js/projects.js":
        from sketchforge.generation.app_specification import EntitySpec, FieldSpec
        entity_obj = EntitySpec(
            main_entity_name,
            [FieldSpec(f.get("name", "title"), f.get("name", "Title")) for f in main_entity_fields],
        )
        return _projects_js(entity_obj, route, storage_key)

    if path_hint == "backend/schema.sql":
        col_sql = ", ".join(f"{f.get('name', 'col')} TEXT" for f in main_entity_fields)
        return f"""-- Generated schema for {name}
CREATE TABLE IF NOT EXISTS {route} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {col_sql},
    created_at TEXT DEFAULT (datetime('now'))
);
"""

    if path_hint == "backend/models.py":
        fields_code = "\n    ".join(f"{f.get('name', 'title')}: str = ''" for f in main_entity_fields)
        return f'''from __future__ import annotations
from dataclasses import dataclass

@dataclass
class {main_entity_name}:
    id: int | None = None
    {fields_code}
    created_at: str | None = None
'''

    if path_hint == "backend/database.py":
        return f'''from __future__ import annotations
import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).parent.parent / "data" / "{route}.db"

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        schema = Path(__file__).parent / "schema.sql"
        if schema.exists():
            conn.executescript(schema.read_text(encoding="utf-8"))
        conn.commit()
        g.db = conn
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
'''

    if path_hint == "backend/logic.py":
        return f'''from __future__ import annotations
from backend.database import get_db

def list_items():
    return [dict(r) for r in get_db().execute("SELECT * FROM {route} ORDER BY id DESC").fetchall()]

def create_item(data: dict):
    db = get_db()
    keys = [k for k in data.keys() if k != "id"]
    cols = ", ".join(keys)
    placeholders = ", ".join("?" for _ in keys)
    vals = [data[k] for k in keys]
    cur = db.execute(f"INSERT INTO {route} ({{cols}}) VALUES ({{placeholders}})", vals)
    db.commit()
    return dict(db.execute("SELECT * FROM {route} WHERE id = ?", (cur.lastrowid,)).fetchone())

def delete_item(item_id: int):
    db = get_db()
    cur = db.execute("DELETE FROM {route} WHERE id = ?", (item_id,))
    db.commit()
    return cur.rowcount > 0
'''

    if path_hint == "backend/api.py":
        from sketchforge.generation.studio_generator import _write_backend_api
        from sketchforge.generation.app_specification import AppSpec, EntitySpec, FieldSpec
        entity_obj = EntitySpec(
            main_entity_name,
            [FieldSpec(f.get("name", "title"), f.get("name", "Title")) for f in main_entity_fields],
        )
        temp_spec = AppSpec(
            name=name,
            description=name,
            entities=[entity_obj],
        )
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            _write_backend_api(tmp_root, temp_spec)
            api_file = tmp_root / "backend" / "api.py"
            if api_file.exists():
                return api_file.read_text(encoding="utf-8")
        from sketchforge.retrieval.patterns import FLASK_CRUD_API_PATTERN
        return FLASK_CRUD_API_PATTERN

    return f"# Fallback template for {path_hint}\n"


def ai_generate_project(
    prompt: str,
    target: Path,
    *,
    include_backend: bool = True,
    sketch_path: Path | str | None = None,
    design_doc: object | None = None,
    layout_block: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path | None:
    """Two-stage AI generation pipeline:

    1. Plan – ask Nemotron for a compact AppSpec (~500 tokens).
    2. Files – generate each dynamic file individually with per-file fallback.

    Never discards AI output: if any individual file fails model generation,
    it is populated from the verified template generator so all 12 files are delivered.
    """
    def _emit(msg: str) -> None:
        log.info("ai_generate: %s", msg)
        if progress:
            progress(msg)

    # 1. Resolve layout block from arguments or prompt
    if layout_block is None:
        if design_doc is not None:
            try:
                from sketchforge.vision.to_design_ir import build_nemotron_layout_block_from_document
                layout_block = build_nemotron_layout_block_from_document(design_doc)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not build layout block from design_doc: %s", exc)
        elif sketch_path is not None:
            try:
                from sketchforge.vision import load_image, analyze
                from sketchforge.vision.to_design_ir import build_nemotron_layout_block
                loaded = load_image(Path(sketch_path))
                res = analyze(loaded)
                layout_block = build_nemotron_layout_block(res, sketch_name=Path(sketch_path).name)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not build layout block from sketch_path: %s", exc)
        else:
            layout_block = _extract_layout_block(prompt)

    layout_context = _format_layout_context(layout_block) if layout_block else ""

    _emit("Connecting to AI service…")
    try:
        client = _make_client()
    except Exception as exc:  # noqa: BLE001
        _emit(f"AI service unavailable ({exc}); using template generator.")
        return None

    # ------------------------------------------------------------------
    # Stage 1 — AppSpec plan
    # ------------------------------------------------------------------
    spec, active_model = _stage1_plan(client, prompt, include_backend, _emit, layout_block=layout_block)
    if spec is None:
        return None

    app_name = spec.get("name") or " ".join(prompt.split()[:3]).title() or "New App"
    slug = re.sub(r"[^a-z0-9]+", "-", app_name.lower()).strip("-")[:48] or "new-app"
    root = target.resolve() / slug
    root.mkdir(parents=True, exist_ok=True)

    spec_str = json.dumps(spec, ensure_ascii=False)

    # Derive the authoritative API route from the spec — used in the Stage-2
    # prompt context so every file (frontend & backend) is consistent.
    entities = spec.get("entities") or []
    main_entity_name = entities[0].get("name", "Submission") if entities else "Submission"
    entity_route = re.sub(r"[^a-z0-9]+", "-", main_entity_name.lower()).strip("-") + "s"
    entity_route_context = (
        f"\n\n### Authoritative API Route (use EXACTLY this route in ALL files):\n"
        f"Entity: {main_entity_name}\n"
        f"Backend table: {re.sub(r'[^a-z0-9_]+', '_', main_entity_name.lower()).strip('_')}\n"
        f"API route: /api/{entity_route}\n"
        f"Frontend JS must POST to /api/{entity_route} and GET from /api/{entity_route}.\n"
        f"Flask backend must expose /api/{entity_route} and /api/{entity_route}/<id>.\n"
    )

    # ------------------------------------------------------------------
    # Stage 2 — per-file generation with per-file fallback
    # ------------------------------------------------------------------
    manifest = _file_manifest(spec)
    _emit(f"Stage 2 — generating {len(manifest)} files individually…")

    written = 0
    fallback_count = 0
    provenance: dict[str, str] = {}  # path_hint -> "ai_generated" | "template_fallback"
    for path_hint, description in manifest:
        _emit(f"  Generating {path_hint} ({written + 1}/{len(manifest)})…")
        import inspect
        _sig = inspect.signature(_stage2_file)
        _s2_kwargs = {
            "model": active_model or _NEMOTRON_MODEL,
            "layout_context": layout_context,
        }
        if "entity_route_context" in _sig.parameters:
            _s2_kwargs["entity_route_context"] = entity_route_context
        elif entity_route_context:
            _s2_kwargs["layout_context"] = (layout_context or "") + entity_route_context

        content = _stage2_file(
            client,
            spec_str,
            path_hint,
            description,
            _emit,
            **_s2_kwargs,
        )
        if content is None or not str(content).strip():
            log.warning("AI model returned no content for %s; using template fallback.", path_hint)
            content = get_fallback_file_content(path_hint, spec)
            provenance[path_hint] = "template_fallback"
            fallback_count += 1
            _emit(f"  Fallback: filled {path_hint} from verified template.")
        else:
            provenance[path_hint] = "ai_generated"

        # Guarantee route alignment: if model emitted /api/submissions, map to entity_route
        if entity_route and entity_route != "submissions" and isinstance(content, str):
            content = content.replace("/api/submissions", f"/api/{entity_route}")

        dest = (root / path_hint).resolve()
        if not dest.is_relative_to(root):
            log.warning("Ignoring model-generated path outside the project: %s", path_hint)
            content = get_fallback_file_content(path_hint, spec)
            provenance[path_hint] = "template_fallback"
            dest = (root / path_hint).resolve()
            fallback_count += 1

        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_text(str(content), encoding="utf-8")
            written += 1
        except OSError as exc:
            log.warning("Could not write %s (%s); writing fallback template.", dest, exc)
            fallback_text = get_fallback_file_content(path_hint, spec)
            dest.write_text(fallback_text, encoding="utf-8")
            provenance[path_hint] = "template_fallback"
            written += 1
            fallback_count += 1

    (root / "data").mkdir(exist_ok=True)
    _ensure_entry(root)

    # Write provenance record so the UI can show AI vs fallback status per file.
    try:
        import json as _json
        ai_count = len(manifest) - fallback_count
        meta = {
            "generation": "ai_generated" if fallback_count == 0 else (
                "template_fallback" if ai_count == 0 else "mixed"
            ),
            "ai_model": active_model or _NEMOTRON_MODEL,
            "total_files": len(manifest),
            "ai_generated_count": ai_count,
            "template_fallback_count": fallback_count,
            "file_provenance": provenance,
        }
        (root / ".sketchforge_meta.json").write_text(
            _json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass  # provenance record is best-effort
    status_summary = (
        f"AI generation complete: {root.name} ({len(manifest)}/{len(manifest)} files written; "
        f"{len(manifest) - fallback_count} from AI, {fallback_count} from fallback template)."
        if fallback_count > 0 else
        f"AI generation complete: {root.name} (100% AI generated, {len(manifest)}/{len(manifest)} files)."
    )
    _emit(status_summary)
    return root


def ai_revise_project(
    project_root: Path,
    instruction: str,
    *,
    progress: Callable[[str], None] | None = None,
) -> bool:
    """
    Ask the LLM to apply a follow-up instruction to an already-generated project.

    Returns True when files were updated, False on any failure.
    """
    def _emit(msg: str) -> None:
        log.info("ai_revise: %s", msg)
        if progress:
            progress(msg)

    _emit("Loading existing project files…")
    existing = _read_project(project_root)
    if not existing:
        _emit("No readable files found in the project.")
        return False

    _emit("Sending revision instruction to the model…")
    try:
        client = _make_client()
    except Exception as exc:  # noqa: BLE001
        _emit(f"AI service unavailable ({exc}).")
        return False

    revise_system = (
        "You are SketchForge Studio's revision assistant.\n"
        "You will receive the current project files (truncated) and a revision instruction.\n"
        "Return ONLY a JSON object with this schema — no extra text, no outer markdown fence:\n"
        '{"files": [{"path": "<rel path>", "content": "<full updated content>"}]}\n'
        "The value of each \"content\" field must be the raw file text as a plain string.\n"
        "If the file content is large, split it into multiple small files rather than\n"
        "producing one giant JSON string that risks being truncated.\n"
        "Include ONLY files that need to change. The JSON must be parseable by json.loads."
    )
    files_summary = json.dumps(
        [{"path": p, "content": c[:400] + "…" if len(c) > 400 else c}
         for p, c in list(existing.items())[:12]]
    )
    user_msg = (
        f"Current project files (truncated):\n{files_summary}\n\n"
        f"Revision instruction: {instruction.strip()}"
    )

    from sketchforge.integrations.provider_interface import ChatMessage, CompletionRequest

    request = CompletionRequest(
        messages=(
            ChatMessage(role="system", content=revise_system),
            ChatMessage(role="user", content=user_msg),
        ),
        purpose="studio_revise",
        max_tokens=2048,
        temperature=0.3,
        model=_NEMOTRON_MODEL,
    )

    try:
        result = client.complete(request)
    except Exception as exc:  # noqa: BLE001
        _emit(f"Revision request failed ({exc}).")
        return False

    _emit("Applying changes…")
    try:
        data = _parse_response(result.text)
    except ValueError as exc:
        _emit(f"Could not parse model response ({exc}).")
        return False

    files = data.get("files", [])
    updated = 0
    for entry in files:
        rel = entry.get("path", "").lstrip("/\\")
        content = entry.get("content", "")
        if not rel:
            continue
        dest = (project_root / rel).resolve()
        if not dest.is_relative_to(project_root.resolve()):
            log.warning("Ignoring model-generated revision path outside the project: %s", rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_text(str(content), encoding="utf-8")
            updated += 1
        except OSError as exc:
            log.warning("Could not write %s: %s", dest, exc)

    _emit(f"Revision applied: {updated} file(s) updated.")
    return updated > 0


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


def _extract_layout_block(prompt: str) -> dict | None:
    """Extract layout_block dictionary from a prompt containing <SketchDesignDocument>."""
    match = re.search(r"<SketchDesignDocument>(.*?)</SketchDesignDocument>", prompt, re.DOTALL)
    if not match:
        return None
    try:
        data = extract_balanced_json(match.group(1).strip())
        return data.get("layout_block")
    except Exception:
        return None


def _format_layout_context(layout_block: dict | None) -> str:
    """Format structured component bounding boxes and hierarchy for LLM prompts."""
    if not layout_block or not isinstance(layout_block, dict):
        return ""
    lines = []
    canvas = layout_block.get("canvas", {})
    if canvas:
        w = canvas.get("width_design_px", "?")
        h = canvas.get("height_design_px", "?")
        dev = canvas.get("device", "desktop")
        lines.append(f"Canvas: {w}x{h} px ({dev})")
    hierarchy = layout_block.get("hierarchy", "")
    if hierarchy:
        lines.append(f"Component Nesting Hierarchy:\n{hierarchy}")
    components = layout_block.get("components", [])
    if components:
        lines.append("Detected Components (design-pixel bounding boxes):")
        for c in components[:25]:
            cid = c.get("id", "")
            ctype = c.get("type", "container")
            bbox = c.get("bbox_design_px", {})
            bx, by, bw, bh = bbox.get("x", 0), bbox.get("y", 0), bbox.get("w", 0), bbox.get("h", 0)
            label = f' label="{c.get("label")}"' if c.get("label") else ""
            lines.append(f"  - [{ctype.upper()}] id={cid} bbox=(x={bx}, y={by}, w={bw}, h={bh}){label}")
    return "\n".join(lines)


def _spec_from_layout_block(prompt: str, layout_block: dict | None = None) -> dict | None:
    """Extract and return a pre-seeded AppSpec dict from the SketchDesignDocument block.

    When the user uploads a sketch before generation, the frontend embeds a
    ``<SketchDesignDocument>`` XML fragment containing a ``layout_block`` with:
    - ``app_spec``   — heuristic AppSpec already derived via ``spec_from_document()``
    - ``components`` — exact design-px bboxes + containment hierarchy
    - ``hierarchy``  — human-readable tree
    - ``canvas``     — canvas dimensions
    """
    if layout_block is None:
        match = re.search(r"<SketchDesignDocument>(.*?)</SketchDesignDocument>", prompt, re.DOTALL)
        if not match:
            return None
        try:
            block_json = json.loads(match.group(1).strip())
        except (ValueError, json.JSONDecodeError):
            return None
        layout_block = block_json.get("layout_block")
        if not layout_block or not isinstance(layout_block, dict):
            regions = block_json.get("regions", [])
            if not regions:
                return None
            inputs = [r for r in regions if r.get("type") == "input"]
            buttons = [r for r in regions if r.get("type") == "button"]
            has_backend = len(inputs) >= 2 and len(buttons) >= 1
            pages = [{"name": "home", "title": "Home", "route": "/"}]
            entities = []
            if has_backend:
                entities = [{"name": "Record", "fields": [{"name": f"field_{i}", "type": "text"} for i in range(len(inputs))]}]
            return {"name": "Sketch App", "pages": pages, "entities": entities, "include_backend": has_backend}

    app_spec = layout_block.get("app_spec", {})
    if not app_spec:
        return None

    # Convert AppSpec dataclass-dict format -> Stage-1 flat format
    pages_raw = app_spec.get("pages", [])
    pages = []
    for p in pages_raw:
        pages.append({
            "name": p.get("name", "home"),
            "title": p.get("title", p.get("name", "Home").title()),
            "route": p.get("route", "/"),
        })
    if not pages:
        pages = [{"name": "home", "title": "Home", "route": "/"}]

    entities_raw = app_spec.get("entities", [])
    entities = []
    for e in entities_raw:
        fields_raw = e.get("fields", [])
        fields = [{"name": f.get("name", "field"), "type": f.get("type", "text")} for f in fields_raw]
        entities.append({"name": e.get("name", "Record"), "fields": fields})

    include_backend = bool(app_spec.get("tech_backend", "none") != "none" or entities)

    return {
        "name": app_spec.get("name", "Sketch App"),
        "pages": pages,
        "entities": entities,
        "include_backend": include_backend,
    }


def _stage1_plan(
    client,
    prompt: str,
    include_backend: bool,
    emit: Callable[[str], None],
    layout_block: dict | None = None,
) -> tuple[dict | None, str | None]:
    """Stage 1: request a compact AppSpec JSON from a single verified Nemotron model."""
    from sketchforge.integrations.provider_interface import ChatMessage, CompletionRequest

    # ------------------------------------------------------------------
    # Extract pre-seeded spec from the sketch layout block (if present).
    # ------------------------------------------------------------------
    seeded_spec = _spec_from_layout_block(prompt, layout_block=layout_block)
    if seeded_spec:
        log.info(
            "Stage 1: pre-seeded spec from sketch layout block — %s page(s), %s entity/entities.",
            len(seeded_spec.get("pages", [])),
            len(seeded_spec.get("entities", [])),
        )

    # ------------------------------------------------------------------
    # Probe once — select a single verified model before planning.
    # ------------------------------------------------------------------
    active_model, probe_err = _select_active_model(client, emit)

    if active_model is None:
        if seeded_spec:
            emit(
                f"[{_ts()}] Stage 1 — all models unreachable ({probe_err}); "
                "using sketch-derived layout as fallback plan."
            )
            log.warning("Stage 1 Nemotron unavailable — falling back to sketch-seeded spec.")
            seeded_spec.setdefault("include_backend", include_backend)
            return seeded_spec, None
        emit(
            f"[{_ts()}] Stage 1 — all models unreachable ({probe_err}); "
            "falling back to template generator."
        )
        return None, None

    # ------------------------------------------------------------------
    # Single plan request against the verified model.
    # ------------------------------------------------------------------
    layout_context = _format_layout_context(layout_block) if layout_block else ""
    layout_snippet = f"\n\n### Grounded Sketch Layout (OpenCV Vision Analysis):\n{layout_context}\n" if layout_context else ""

    user_msg = _PLAN_USER.format(
        brief=prompt.strip(),
        backend="yes" if include_backend else "no",
    ) + layout_snippet
    short_model = active_model.split("/")[-1]
    emit(f"[{_ts()}] Stage 1 — requesting AppSpec plan from {short_model}…")

    request = CompletionRequest(
        messages=(
            ChatMessage(role="system", content=_PLAN_SYSTEM),
            ChatMessage(role="user", content=user_msg),
        ),
        purpose="studio_plan",
        max_tokens=4096,
        temperature=0.2,
        model=active_model,
    )
    try:
        result = client.complete(request)
        spec = _parse_response(result.text)
    except Exception as exc:  # noqa: BLE001
        failure_reason = f"{type(exc).__name__}: {exc}"
        log.warning("Stage 1 plan request with %s failed: %s", active_model, exc)
        if seeded_spec:
            emit(
                f"[{_ts()}] Stage 1 — plan request failed ({failure_reason}); "
                "using sketch-derived layout as fallback plan."
            )
            seeded_spec.setdefault("include_backend", include_backend)
            return seeded_spec, None
        emit(
            f"[{_ts()}] Stage 1 — plan request failed ({failure_reason}); "
            "falling back to template generator."
        )
        return None, None

    # ------------------------------------------------------------------
    # Merge: use the model's enriched spec but honour seeded values for
    # any field the model left empty or omitted.
    # ------------------------------------------------------------------
    if seeded_spec:
        if not spec.get("pages"):
            spec["pages"] = seeded_spec["pages"]
        if not spec.get("entities"):
            spec["entities"] = seeded_spec["entities"]
        if not spec.get("name") or spec["name"] in {"Sketch App", "GeneratedApp"}:
            spec["name"] = seeded_spec.get("name", spec.get("name", "Sketch App"))
        spec.setdefault("include_backend", seeded_spec.get("include_backend", include_backend))

    emit(
        f"[{_ts()}] Stage 1 complete — app: '{spec.get('name', '?')}', "
        f"{len(spec.get('pages', []))} page(s), "
        f"{len(spec.get('entities', []))} entity/entities."
    )
    return spec, active_model


def _stage2_file(
    client,
    spec_str: str,
    path_hint: str,
    description: str,
    emit: Callable[[str], None],
    model: str = _NEMOTRON_MODEL,
    layout_context: str | None = None,
    entity_route_context: str | None = None,
) -> str | None:
    """Stage 2: generate ONE file and return its content string, or None on failure."""
    from sketchforge.integrations.provider_interface import ChatMessage, CompletionRequest
    from sketchforge.retrieval.code_retriever import retrieve_code_pattern

    pattern = retrieve_code_pattern(path_hint, description)
    rag_section = ""
    if pattern:
        if entity_route_context:
            m = re.search(r"API route:\s*/api/([a-zA-Z0-9_\-]+)", entity_route_context)
            if m:
                r_slug = m.group(1)
                pattern = pattern.replace("/api/submissions", f"/api/{r_slug}")
        rag_section = (
            f"\n\n### Verified Reference Pattern (RAG):\n"
            f"The following verified pattern demonstrates conventions (CORS, token auth, layout, styling):\n"
            f"```\n{pattern}\n```\n"
            f"Follow the architectural conventions shown above for {path_hint}."
        )

    layout_section = ""
    if layout_context and any(path_hint.endswith(ext) for ext in (".html", ".css")):
        layout_section = (
            f"\n\n### Grounded Design Geometry (OpenCV Vision Analysis):\n"
            f"{layout_context}\n"
            f"Faithfully reproduce these component bounding boxes, alignments, and hierarchy in {path_hint}."
        )

    # Always include the entity route context so every file uses the same endpoint.
    route_section = entity_route_context or ""

    user_msg = _FILE_USER.format(
        spec=spec_str,
        path=path_hint,
        description=description,
    ) + layout_section + rag_section + route_section

    request = CompletionRequest(
        messages=(
            ChatMessage(role="system", content=_FILE_SYSTEM),
            ChatMessage(role="user", content=user_msg),
        ),
        purpose="studio_file",
        max_tokens=4096,
        temperature=0.2,
        model=model,
    )
    try:
        result = client.complete(request)
    except Exception as exc:  # noqa: BLE001
        log.warning("Stage 2 request for %s failed: %s", path_hint, exc)
        return None

    return _parse_file_content(result.text, path_hint)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_client():
    """Build and return a NebiusClient with the API key from the environment."""
    from sketchforge.integrations.nebius.client import NebiusClient
    from sketchforge.integrations.nebius.configuration import load_nebius_config
    from sketchforge.integrations.nebius.request_policy import ConsentGate

    config = load_nebius_config(overrides={"enabled": True, "timeout_s": 35.0, "max_retries": 1})
    consent = ConsentGate(consented=True)
    return NebiusClient(config, consent)


def extract_balanced_json(text: str) -> dict:
    """Extract and parse the first valid, balanced JSON object from text.

    Replaces fragile regexes that fail on nested braces or trailing text.
    Correctly handles nested object structures, arrays, and string escapes.
    """
    if not text or not text.strip():
        raise ValueError("Empty response text")

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"<reasoning>.*?</reasoning>", "", cleaned, flags=re.DOTALL).strip()

    # If wrapped in markdown json fences, prioritize content inside fences
    fence_matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    candidates = fence_matches + [cleaned]

    for candidate in candidates:
        candidate_len = len(candidate)
        for start_idx in range(candidate_len):
            if candidate[start_idx] != "{":
                continue
            depth = 0
            in_string = False
            escape = False
            for i in range(start_idx, candidate_len):
                ch = candidate[i]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            slice_str = candidate[start_idx : i + 1]
                            try:
                                parsed = json.loads(slice_str)
                                if isinstance(parsed, dict):
                                    return parsed
                            except json.JSONDecodeError:
                                break

    # Fallback to direct json.loads if string is already clean JSON
    for candidate in candidates:
        stripped = candidate.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

    raise ValueError("No valid JSON object found in model response")


def _parse_file_content(text: str, path_hint: str) -> str | None:
    """Extract file content from a markdown code fence, JSON envelope, or raw output.

    Priority order (highest first):
      1. Closed markdown code fences: ```<lang>\n<code>\n```
      2. Unclosed / truncated markdown code fences (cut off by max_tokens)
      3. JSON envelope {"path": "...", "content": "..."} via extract_balanced_json
      4. Raw text output
    """
    if not text or not text.strip():
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"<reasoning>.*?</reasoning>", "", cleaned, flags=re.DOTALL).strip()

    # 1. Closed markdown code fences
    fences = re.findall(r"```(?:[a-zA-Z0-9_\-]*)[ \t]*\r?\n([\s\S]*?)\r?\n```", cleaned)
    if fences:
        return max(fences, key=len).strip()

    # 2. Unclosed markdown code fence (cut off by max_tokens)
    unclosed = re.search(r"```(?:[a-zA-Z0-9_\-]*)[ \t]*\r?\n([\s\S]+)$", cleaned)
    if unclosed:
        code = unclosed.group(1).rstrip()
        code = re.sub(r"\n?`{1,3}$", "", code).strip()
        if code:
            log.info("_parse_file_content: accepted unclosed code fence for %s", path_hint)
            return code

    # 3. JSON envelope fallback {"path": "...", "content": "..."}
    try:
        data = extract_balanced_json(cleaned)
        content = data.get("content")
        if isinstance(content, str) and content.strip():
            log.debug("_parse_file_content: fell back to JSON envelope for %s", path_hint)
            return content
    except Exception:
        pass

    # 4. Raw code content (if not a JSON wrapper)
    if not (cleaned.startswith("{") and cleaned.endswith("}") and '"' in cleaned):
        log.debug("_parse_file_content: using raw output for %s", path_hint)
        return cleaned

    return None


def _parse_response(text: str) -> dict:
    """Extract and parse the first JSON object from the model's response text."""
    return extract_balanced_json(text)


def _read_project(root: Path) -> dict[str, str]:
    """Read all text files in the project (limited to avoid huge payloads)."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".html", ".css", ".js", ".py", ".sql", ".md", ".json"}:
            try:
                out[str(path.relative_to(root))] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    return out


def _ensure_entry(root: Path) -> None:
    """Make sure at least an index.html redirect exists."""
    index = root / "index.html"
    if not index.exists():
        home = root / "home.html"
        target = "home.html" if home.exists() else "index.html"
        index.write_text(
            f'<!doctype html><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0; url={target}">'
            f'<title>Opening app…</title><a href="{target}">Open the app</a>',
            encoding="utf-8",
        )
