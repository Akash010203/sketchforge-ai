"""Create a runnable, local-first web app project from a short product brief.

Generation order:
  1. AI generator (Nebius/OpenAI-compatible) — full-stack files tailored to the brief.
  2. Template generator (always available) — polished fallback when AI is offline.
"""

from __future__ import annotations

import re
import json
from html import escape
from pathlib import Path
from typing import Callable

from sketchforge.generation.app_specification import AppSpec, EntitySpec, FieldSpec, PageSpec
from sketchforge.generation.file_tree import materialise
from sketchforge.generation.project_planner import plan_html_css


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48] or "new-app"


def _extract_entities_from_brief(prompt: str) -> list[EntitySpec]:
    """Choose a useful data model from known domains or a custom prompt noun."""
    brief = prompt.lower()

    def matches(*keywords: str) -> bool:
        return any(
            re.search(rf"\b{re.escape(word)}(?:s|es)?\b", brief)
            for word in keywords
        )

    if matches("task", "todo", "project"):
        return [EntitySpec("Task", [
            FieldSpec("title", "Title"),
            FieldSpec("priority", "Priority", "select", options=["Low", "Medium", "High"]),
            FieldSpec("due_date", "Due date", "date", required=False),
            FieldSpec("status", "Status", "select", options=["Todo", "In progress", "Done"]),
        ])]
    if matches("book", "store", "shop", "catalog", "product", "inventory"):
        return [EntitySpec("Product", [
            FieldSpec("title", "Title"),
            FieldSpec("price", "Price", "number"),
            FieldSpec("category", "Category"),
            FieldSpec("stock", "Stock", "number"),
        ])]
    if matches("clinic", "yoga", "appointment", "booking", "reservation", "schedule"):
        return [EntitySpec("Booking", [
            FieldSpec("client_name", "Client name"),
            FieldSpec("date", "Date", "date"),
            FieldSpec("service", "Service"),
            FieldSpec("status", "Status", "select", options=["Requested", "Confirmed", "Completed"]),
        ])]
    if matches("event", "conference", "meetup", "webinar"):
        return [EntitySpec("Event", [
            FieldSpec("title", "Title"),
            FieldSpec("date", "Date", "date"),
            FieldSpec("location", "Location"),
            FieldSpec("description", "Description", required=False),
        ])]
    if matches("customer", "client", "contact", "lead"):
        return [EntitySpec("Contact", [
            FieldSpec("name", "Name"),
            FieldSpec("email", "Email", "email"),
            FieldSpec("company", "Company", required=False),
            FieldSpec("notes", "Notes", required=False),
        ])]
    if matches("invoice", "payment", "billing", "expense"):
        return [EntitySpec("Invoice", [
            FieldSpec("title", "Title"),
            FieldSpec("amount", "Amount", "number"),
            FieldSpec("due_date", "Due date", "date", required=False),
            FieldSpec("status", "Status", "select", options=["Pending", "Paid", "Overdue"]),
        ])]
    if matches("note", "journal", "diary"):
        return [EntitySpec("Note", [
            FieldSpec("title", "Title"),
            FieldSpec("content", "Content"),
            FieldSpec("category", "Category", required=False),
        ])]

    # For domains without a specialized schema, infer the record noun from common
    # app briefs: "recipe organizer", "track supplies", or "manage equipment".
    ignored = {"app", "apps", "website", "websites", "platform", "system", "tool", "tools", "workspace"}
    noun = None
    patterns = (
        r"\b(?:track|manage|organize|organise|catalog|log|review|plan)\s+(?:my|our|the|all|your)\s+([a-z][a-z-]*)\b",
        r"\b(?:a|an)\s+(?:[a-z][a-z-]*\s+){0,2}([a-z][a-z-]*)\s+(?:organizer|organiser|manager|tracker|planner|catalog|directory|library|log)\b",
        r"\b(?:for|to)\s+(?:tracking|managing|organizing|organising|cataloging|cataloguing)\s+([a-z][a-z-]*)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, brief)
        if match and match.group(1) not in ignored:
            noun = match.group(1)
            break
    if noun:
        if noun.endswith("ies") and len(noun) > 4:
            noun = noun[:-3] + "y"
        elif noun.endswith("s") and not noun.endswith(("ss", "us", "is")) and len(noun) > 3:
            noun = noun[:-1]
        entity_name = noun.replace("-", " ").title().replace(" ", "")
        return [EntitySpec(entity_name, [
            FieldSpec("title", f"{noun.replace('-', ' ').title()} name"),
            FieldSpec("description", "Description", required=False),
            FieldSpec("category", "Category", required=False),
            FieldSpec("created_at", "Created at", "datetime-local", required=False),
        ], timestamps=False)]

    return [EntitySpec("Item", [
        FieldSpec("title", "Title"),
        FieldSpec("description", "Description", required=False),
        FieldSpec("created_at", "Created at", "datetime-local", required=False),
    ], timestamps=False)]


def generate_studio_project(
    prompt: str,
    target: Path,
    *,
    include_backend: bool = True,
    database: str = "sqlite",
    orm: str = "dataclass",
    api_target: str = "flask",
    authentication: bool = False,
    migrations: bool = False,
    try_ai: bool = True,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Materialise frontend and optional configurable backend files under ``target``.

    Tries AI generation first; falls back to the template generator when the
    AI service is unavailable or returns unusable output.
    """
    brief = prompt.strip()
    if not brief:
        raise ValueError("Describe the app you want to build first.")

    # AI-generated output has a fixed Flask/SQLite contract; use the canonical
    # target renderers whenever the user selected another backend combination.
    if try_ai and (database, orm, api_target, authentication, migrations) == ("sqlite", "dataclass", "flask", False, False):
        try:
            from sketchforge.generation.ai_generator import ai_generate_project
            ai_root = ai_generate_project(brief, target, include_backend=include_backend, progress=progress)
            if ai_root is not None and ai_root.is_dir():
                return ai_root
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("AI generation failed (%s); using templates.", exc)
            if progress:
                progress(f"AI generation unavailable ({exc}); generating from templates...")

    # --- Template fallback path ---
    if progress:
        progress("Generating project from templates...")

    name = " ".join(brief.split()[:3]).strip(".,:;!?—-").title() or "New App"
    entities = _extract_entities_from_brief(brief) if include_backend else []
    fields = entities[0].fields if entities else _extract_entities_from_brief(brief)[0].fields
    pages = [
        PageSpec(
            name="home",
            title=name,
            route="/",
            description=brief,
            forms=[fields],
        ),
        PageSpec(name="projects", title="Your workspace", route="/projects",
                 description="A calm place to keep your work moving."),
    ]
    spec = AppSpec(
        name=name,
        description=brief,
        pages=pages,
        entities=entities,
        tech_frontend="html-css-js",
        tech_backend="python-sqlite" if include_backend else "none",
        database=database,
        orm=orm,
        api_target=api_target,
        authentication=authentication,
        migrations=migrations,
        acceptance_criteria=["Responsive pages render locally", "Forms validate and save submissions"]
    )
    root = target.resolve() / _slug(name)
    materialise(plan_html_css(spec), root)

    if include_backend:
        from sketchforge.generation.frontend.project_export import render_file
        # Reuse the canonical backend plan to keep Studio and planner generation aligned.
        from sketchforge.generation.project_planner import plan_react_ts
        canonical = plan_react_ts(spec)
        backend_files = [f for f in canonical.files if f.generator.startswith("backend_")]
        for planned in backend_files:
            path = planned.relative_path
            content = render_file(planned, canonical)
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content or "", encoding="utf-8")
    _write_frontend(root, spec)
    if include_backend and orm != "prisma":
        from sketchforge.generation.backend.schema_generator import _requirements
        (root / "requirements.txt").write_text(_requirements(spec), encoding="utf-8")
    backend_notes = (
        f"- `backend/prisma/schema.prisma`: Prisma schema; run `cd backend && npm install && npm run db:migrate`.\n"
        if include_backend and orm == "prisma" else
        f"- `backend/`: {database} schema, generated models/CRUD, {api_target} API, and optional auth.\n"
        f"- Install API dependencies with `python -m pip install -r requirements.txt`.\n"
        f"- Start Flask with `python -m backend.api`; start FastAPI/GraphQL with `uvicorn backend.api:app`.\n"
        f"- Set `DATABASE_URL` for PostgreSQL/MySQL. Set `AUTH_SECRET` for authentication. "
        f"Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to enable Google OAuth2."
        f"{' Apply schema changes with `alembic upgrade head`.' if migrations else ''}"
        if include_backend else "- Backend generation was not selected."
    )
    backend_start = (
        "Backend generation was not selected."
        if not include_backend else
        "Run `cd backend && npm install && npm run db:migrate` for the Prisma database client."
        if orm == "prisma" else
        "Run `uvicorn backend.api:app` for FastAPI/GraphQL, or `python -m backend.api` for Flask."
    )
    main_entity = spec.entities[0] if spec.entities else EntitySpec("Submission", [])
    entity_route = _slug(main_entity.name) + "s"
    entity_name_lower = main_entity.name.lower()
    (root / "README.md").write_text(f"""# {name}

Responsive HTML, CSS, and JavaScript generated by SketchForge Studio.

## Frontend

Open `index.html` directly, or run a local static server from this directory:

```bash
python -m http.server 8000
```

Then visit `http://localhost:8000`.

## Backend API

{backend_start}

When generated from within SketchForge Studio, supported API backends start automatically for preview.

## Project files

- `home.html`, `projects.html`: linked app screens.
- `css/style.css`: responsive design system and page styles.
- `js/home.js`: form submission that POSTs to /api/{entity_route}.
- `js/projects.js`: fetches and renders {entity_name_lower} records from /api/{entity_route}.
{"- Install backend dependencies with `python -m pip install -r requirements.txt`." if include_backend else ""}
{backend_notes}
""", encoding="utf-8")
    # The Studio must tell users which generator actually produced the project.
    (root / ".sketchforge_meta.json").write_text(
        json.dumps({
            "generation": "template_fallback",
            "ai_generated_count": 0,
            "template_fallback_count": len(list(root.rglob("*"))),
        }, indent=2),
        encoding="utf-8",
    )
    return root


def _write_frontend(root: Path, spec: AppSpec) -> None:
    """Give generated pages a polished, responsive surface with working navigation/forms."""
    entity = spec.entities[0] if spec.entities else _extract_entities_from_brief(spec.description)[0]
    route = _slug(entity.name) + "s"
    storage_key = f"sketchforge-{route}"
    for page in spec.pages:
        slug = page.name.lower()
        safe_name = escape(spec.name)
        safe_title = escape(page.title)
        safe_description = escape(page.description)
        html_path = root / f"{slug}.html"
        nav = "".join(
            f'<a href="{other.name.lower()}.html">{escape(other.title) if other.name != page.name else "Overview"}</a>'
            for other in spec.pages
        )
        inputs = []
        for field_spec in entity.fields:
            label = escape(field_spec.label)
            field_name = escape(field_spec.name)
            required = " required" if field_spec.required else ""
            if field_spec.type == "select":
                choices = "".join(
                    f'<option value="{escape(option)}">{escape(option)}</option>'
                    for option in field_spec.options
                )
                control = f'<select name="{field_name}"{required}>{choices}</select>'
            else:
                input_type = field_spec.type if field_spec.type in {
                    "text", "email", "number", "date", "datetime-local", "password"
                } else "text"
                control = f'<input name="{field_name}" type="{input_type}" placeholder="{escape(field_spec.placeholder)}"{required}>'
            inputs.append(f'<label>{label}{control}</label>')
        form = (
            f'<form id="idea-form">{"".join(inputs)}'
            f'<button class="primary" type="submit">Add {escape(entity.name.lower())} <span>↗</span></button>'
            '<p class="form-note" id="form-note">Records save to your workspace.</p></form>'
        ) if page.name == "home" else ""
        suggestions = (
            '<div class="ideas"><span class="idea-label">NEED A PLACE TO START?</span>'
            '<button type="button" class="idea-chip" data-idea="A thoughtful client portal for my small studio">A home for my client work <b>↗</b></button>'
            '<button type="button" class="idea-chip" data-idea="A simple habit tracker that feels good to use">A tiny habit tracker <b>↗</b></button>'
            '<button type="button" class="idea-chip" data-idea="A modern dashboard for my team projects">A calmer team dashboard <b>↗</b></button></div>'
            if page.name == "home" else
            '<div class="ideas"><a class="idea-chip" href="home.html">Start another idea <b>↗</b></a></div>'
        )
        html_path.write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{safe_description}"><title>{safe_title} · {safe_name}</title><link rel="stylesheet" href="css/style.css"></head>
<body><header class="top"><a class="brand" href="home.html"><span class="brand-mark">s</span>{safe_name}</a><nav>{nav}</nav><button class="avatar" aria-label="Account">A</button></header>
<main><div class="eyebrow"><span class="spark">✳</span> YOUR NEXT IDEA, IN MOTION</div>
<section class="hero"><div class="hero-copy"><p class="kicker">A little more room to imagine</p><h1>{safe_title}<br><em>starts right here.</em></h1>
<p class="lede">{safe_description}</p><div class="proof"><span class="avatars"><i>A</i><i>M</i><i>J</i></span><span>Made for the way you think.</span><span class="proof-dot">·</span><span>Ready when you are.</span></div></div>
<aside class="welcome-card"><div class="card-top"><span class="card-icon">✳</span><span class="live-pill"><i></i> YOUR CANVAS</span></div><div class="orb orb-one"></div><div class="orb orb-two"></div><div class="card-art"><div class="art-window"><div class="art-nav"><b></b><span></span><span></span><span></span></div><div class="art-lines"><i></i><i></i><i></i></div><div class="art-blocks"><b></b><b></b><b></b></div></div><span class="float-chip">✦ &nbsp; good ideas live here</span></div><div class="card-foot"><span>BUILT AROUND YOUR IDEA</span><span>01 — 02</span></div></aside></section>
<section class="work"><div class="work-heading"><div><span class="kicker">THE FIRST STEP IS EASY</span><h2>What are we making?</h2></div><span class="counter">01 <i>/</i> 02</span></div>
<div class="builder"><div class="builder-head"><div class="builder-label"><span class="status-dot"></span><b>Tell us a little about it</b><span class="muted">· takes one sentence</span></div><span class="private">⌁ &nbsp; Private workspace</span></div>
{form if page.name == "home" else f'<p class="lede">Your {escape(entity.name.lower())} records, ready to explore.</p><ul id="submissions-list" class="submission-list"></ul>'}
{suggestions}</div></section>
<footer><span>✳ &nbsp;SketchForge Studio</span><span>Made to move at the speed of your ideas&nbsp; ↗</span></footer></main><script src="js/{slug}.js"></script></body></html>''', encoding="utf-8")
        (root / "js" / f"{slug}.js").write_text(
            _home_js(entity, route, storage_key) if slug == "home" else _projects_js(entity, route, storage_key),
            encoding="utf-8",
        )
    (root / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=home.html">'  # noqa: E501
        '<title>Opening app\u2026</title><a href="home.html">Open the app</a>',
        encoding="utf-8",
    )
    (root / "css" / "style.css").write_text(_studio_css(), encoding="utf-8")


def _home_js(entity: EntitySpec, route: str, storage_key: str) -> str:
    template = """\
// Form handler generated for the selected data entity.
document.querySelectorAll('[data-idea]').forEach(button => button.addEventListener('click', () => {
  const field = document.querySelector('[name="title"]');
  if (field) { field.value = button.dataset.idea; field.focus(); }
}));
const form = document.querySelector('#idea-form');
if (form) form.addEventListener('submit', async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  if ('created_at' in __FIELDS__) data.created_at = new Date().toISOString();
  const note = document.querySelector('#form-note');
  const btn = form.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const resp = await fetch('/api/__ROUTE__', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    note.textContent = 'Saved to the database.';
  } catch (error) {
    note.textContent = `Could not save: backend unavailable (${error.message}).`;
    note.classList.remove('success');
    btn.disabled = false;
    btn.textContent = 'Try again';
    return;
  }
  note.classList.add('success');
  btn.textContent = 'Saved ✓';
});
"""
    fields = json.dumps([field.name for field in entity.fields])
    return (template.replace("__FIELDS__", fields)
            .replace("__ROUTE__", route)
            .replace("__STORAGE__", storage_key))


def _projects_js(entity: EntitySpec, route: str, storage_key: str) -> str:
    template = """\
const fields = __FIELDS__;
async function loadRecords() {
  const list = document.querySelector('#submissions-list');
  if (!list) return;
  let items;
  try {
    const response = await fetch('/api/__ROUTE__');
    if (!response.ok) throw new Error('backend unavailable');
    items = await response.json();
  } catch {
    list.innerHTML = '<li class="empty-row">Backend unavailable. Start the generated API and reload this page.</li>';
    return;
  }
  if (!items.length) { list.innerHTML = '<li class="empty-row">No records yet. Add one from the home page.</li>'; return; }
  list.innerHTML = items.map((item,index) => `<li class="submission-card">${fields.map(field =>
    `<span class="sub-idea"><b>${field.replaceAll('_',' ')}</b>: ${escapeHtml(String(item[field] ?? '—'))}</span>`
  ).join('')}<button class="delete-btn" data-id="${item.id ?? ''}" data-index="${index}">✕</button></li>`).join('');
  list.querySelectorAll('.delete-btn').forEach(button => button.addEventListener('click', async () => {
    if (!button.dataset.id) return;
    const response = await fetch(`/api/__ROUTE__/${button.dataset.id}`, {method:'DELETE'});
    if (!response.ok) { list.insertAdjacentHTML('afterbegin', '<li class="empty-row">Could not delete the record. Check the backend and try again.</li>'); return; }
    loadRecords();
  }));
}
function escapeHtml(value) { return value.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
loadRecords();
"""
    fields = json.dumps([field.name for field in entity.fields])
    return (template.replace("__FIELDS__", fields)
            .replace("__ROUTE__", route)
            .replace("__STORAGE__", storage_key))


def _write_backend_api(root: Path, spec: AppSpec) -> None:
    """Write a Flask CRUD REST API to backend/api.py in the generated project.

    Routes use the entity-derived table name (e.g. /api/tasks, /api/products)
    so the generated frontend JavaScript (home.js / projects.js) can reach them
    without hard-coding an unrelated endpoint name.
    """
    from sketchforge.generation.backend.schema_generator import _snake
    entity = spec.entities[0] if spec.entities else None
    table = _snake(entity.name) if entity else "submission"
    # route = plural of table name (e.g. "task" -> "tasks")
    api_route = table + "s"
    fields = [f.name for f in entity.fields] if entity else ["email", "idea"]
    col_defs = ", ".join(f"{n} TEXT" for n in fields)
    insert_cols = ", ".join(fields)
    insert_placeholders = ", ".join("?" for _ in fields)
    insert_values = ", ".join(f"data.get('{n}', '')" for n in fields)

    api_py = '''\
"""Flask CRUD REST API — generated by SketchForge Studio."""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from flask import Flask, g, jsonify, request

app = Flask(__name__)
DB_PATH = Path(__file__).parent.parent / "data" / "__DBNAME__.db"

# ---------------------------------------------------------------------------
# Security: restricted CORS + ephemeral session-token gate
# ---------------------------------------------------------------------------
# CORS_ORIGIN is injected at startup by SketchForge Studio and set to the
# exact preview-server origin (e.g. "http://127.0.0.1:PORT").  Wildcard (*)
# is only used when the env-var is absent so a bare `python backend/api.py`
# still works during manual development.
_ALLOWED_ORIGIN: str = os.environ.get("CORS_ORIGIN", "null")

# STUDIO_TOKEN is an ephemeral secret generated per preview session.  Every
# /api/ request must supply it in the X-Studio-Token header; requests without
# the token receive 401 before any application logic runs.
_STUDIO_TOKEN: str | None = os.environ.get("STUDIO_TOKEN") or None


@app.before_request
def _require_token():
    """Reject /api/* requests that do not carry the correct session token."""
    if not request.path.startswith("/api/") or request.path in ("/api/health", "/health"):
        return  # health / static routes pass through
    if request.method == "OPTIONS":
        return  # CORS pre-flight must not be gated
    if _STUDIO_TOKEN is None:
        return  # token gate disabled (e.g. running outside Studio preview)
    supplied = request.headers.get("X-Studio-Token", "")
    if not supplied or supplied != _STUDIO_TOKEN:
        return jsonify(error="unauthorized"), 401


def _cors(response):
    """Attach restricted CORS headers to every response."""
    # Only reflect the exact allowed origin, never a wildcard.
    if _ALLOWED_ORIGIN and _ALLOWED_ORIGIN != "null":
        response.headers["Access-Control-Allow-Origin"] = _ALLOWED_ORIGIN
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Studio-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Vary"] = "Origin"
    return response


app.after_request(_cors)


@app.route("/api/<path:path>", methods=["OPTIONS"])
def _preflight(path):
    return app.make_default_options_response()


def _db() -> sqlite3.Connection:
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS __TABLE__ "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, __COL_DEFS__, "
            "created_at TEXT DEFAULT (datetime(\'now\')))"
        )
        conn.commit()
        g.db = conn
    return g.db


@app.teardown_appcontext
def _close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.route("/api/__ROUTE__", methods=["GET"])
def list_items():
    rows = _db().execute(
        "SELECT * FROM __TABLE__ ORDER BY id DESC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/__ROUTE__", methods=["POST"])
def create_item():
    data = request.get_json(force=True) or {}
    db = _db()
    cols = __INSERT_COLS__
    placeholders = __PLACEHOLDERS__
    vals = [data.get(k, "") for k in cols]
    cur = db.execute(
        f"INSERT INTO __TABLE__ ({', '.join(cols)}) VALUES ({', '.join(placeholders)})",
        vals,
    )
    db.commit()
    row = db.execute("SELECT * FROM __TABLE__ WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/__ROUTE__/<int:item_id>", methods=["GET"])
def get_item(item_id: int):
    row = _db().execute("SELECT * FROM __TABLE__ WHERE id = ?", (item_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


@app.route("/api/__ROUTE__/<int:item_id>", methods=["PUT"])
def update_item(item_id: int):
    data = request.get_json(force=True) or {}
    db = _db()
    updates = {k: v for k, v in data.items() if k not in ("id", "created_at")}
    if not updates:
        return jsonify({"error": "nothing to update"}), 400
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [item_id]
    db.execute(f"UPDATE __TABLE__ SET {set_clause} WHERE id = ?", vals)
    db.commit()
    row = db.execute("SELECT * FROM __TABLE__ WHERE id = ?", (item_id,)).fetchone()
    return jsonify(dict(row)) if row else (jsonify({"error": "not found"}), 404)


@app.route("/api/__ROUTE__/<int:item_id>", methods=["DELETE"])
def delete_item(item_id: int):
    db = _db()
    cur = db.execute("DELETE FROM __TABLE__ WHERE id = ?", (item_id,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "not found"}), 404
    return "", 204


@app.route("/api/health", methods=["GET"])
def health():
    """Health-check endpoint for the Studio preview readiness probe."""
    return jsonify({"status": "ok", "table": "__TABLE__"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    print(f"SketchForge API running on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)
'''
    # Build the column/field metadata for safe substitution
    fields_list_literal = repr(fields)           # e.g. ["title", "priority"]
    placeholders_list_literal = repr(["?"] * len(fields))

    db_name = _snake(spec.name)
    api_py = (api_py
              .replace("__DBNAME__", db_name)
              .replace("__TABLE__", table)
              .replace("__COL_DEFS__", col_defs)
              .replace("__ROUTE__", api_route)
              .replace("__INSERT_COLS__", fields_list_literal)
              .replace("__PLACEHOLDERS__", placeholders_list_literal)
              )
    dest = root / "backend" / "api.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(api_py, encoding="utf-8")
    # Ensure data directory exists
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / ".gitkeep").write_text("", encoding="utf-8")


def _studio_css() -> str:
    return ''':root{font-family:'Segoe UI',sans-serif;color:#f1f0f5;background:#111116;font-synthesis:none;text-rendering:optimizeLegibility}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse 65% 38% at 80% 3%,#29243a 0%,transparent 72%),radial-gradient(ellipse 48% 32% at 4% 78%,#191b28 0%,transparent 70%),#111116}.top{height:72px;border-bottom:1px solid #ffffff12;display:flex;align-items:center;padding:0 5.5%;gap:40px}.brand{font:700 17px 'Segoe UI',sans-serif;letter-spacing:-.6px;color:#f6f4fa;text-decoration:none;display:flex;align-items:center;gap:10px}.brand-mark{width:27px;height:27px;border-radius:9px;background:#d9ff5f;color:#17180f;display:grid;place-items:center;font-size:18px}.top nav{display:flex;gap:28px;margin:auto;font-size:12px;color:#aaa7b3}.top nav a{color:inherit;text-decoration:none}.avatar{border:1px solid #ffffff25;background:#282730;color:white;border-radius:50%;width:32px;height:32px}.top button,button{font:inherit}.top .avatar{cursor:pointer}main{max-width:1080px;margin:auto;padding:42px 54px 0}.eyebrow,.kicker,.idea-label{font-size:10px;letter-spacing:1.45px;font-weight:700;color:#aba7b7}.eyebrow{display:flex;align-items:center;gap:8px}.spark{color:#d9ff5f;font-size:14px}.hero{display:grid;grid-template-columns:1.04fr .96fr;gap:54px;align-items:center;padding:28px 0 43px}.hero-copy{padding:18px 0}.kicker{color:#c5c2ce;letter-spacing:.35px}.hero h1{font:600 clamp(42px,5.1vw,66px)/1.07 'Segoe UI',sans-serif;letter-spacing:-3.5px;margin:14px 0 18px}.hero h1 em{font-weight:400;color:#d9ff5f;font-style:normal}.lede{font-size:15px;line-height:1.72;color:#b4b1bf;max-width:440px}.proof{display:flex;align-items:center;gap:9px;margin-top:25px;color:#9b98a4;font-size:10px}.avatars{display:flex;padding-left:3px}.avatars i{font-style:normal;width:22px;height:22px;border:2px solid #111116;margin-left:-4px;border-radius:50%;display:grid;place-items:center;background:#33344c;color:#d9ff5f;font-size:9px}.avatars i:nth-child(2){background:#514050;color:#f6ceaf}.avatars i:nth-child(3){background:#304148;color:#b1e9df}.proof-dot{color:#d9ff5f}.welcome-card{height:286px;position:relative;border:1px solid #ffffff1a;border-radius:20px;background:linear-gradient(135deg,#22212c,#181820 67%);overflow:hidden;padding:18px 21px;box-shadow:0 28px 80px #0005}.card-top,.card-foot{display:flex;justify-content:space-between;align-items:center;position:relative;z-index:1}.card-icon{width:27px;height:27px;border-radius:9px;background:#d9ff5f;color:#17180f;display:grid;place-items:center}.live-pill{font-size:8px;color:#acabb5;letter-spacing:1px}.live-pill i,.status-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:#d9ff5f;margin-right:6px;box-shadow:0 0 10px #d9ff5f}.orb{position:absolute;border-radius:50%;filter:blur(35px);opacity:.7}.orb-one{background:#7760d4;width:130px;height:130px;top:105px;left:50px}.orb-two{background:#92b544;width:90px;height:90px;right:40px;top:115px;opacity:.35}.card-art{position:absolute;inset:54px 32px 39px;display:grid;place-items:center}.art-window{width:76%;height:154px;border-radius:11px;background:#111218ed;border:1px solid #ffffff28;padding:13px;box-shadow:0 18px 45px #0007;transform:rotate(-4deg)}.art-nav{display:flex;gap:8px;align-items:center;border-bottom:1px solid #ffffff17;padding-bottom:10px}.art-nav b{width:12px;height:12px;border-radius:4px;background:#d9ff5f}.art-nav span{width:27px;height:4px;border-radius:4px;background:#4d4a58}.art-lines{padding:14px 4px;display:grid;gap:7px}.art-lines i{height:5px;border-radius:4px;background:#bab3cd;width:60%}.art-lines i:nth-child(2){width:43%;background:#d9ff5f}.art-lines i:nth-child(3){width:53%;background:#575364}.art-blocks{display:flex;gap:7px}.art-blocks b{height:30px;flex:1;border-radius:5px;background:#272632}.art-blocks b:first-child{background:#342e48}.art-blocks b:last-child{background:#303628}.float-chip{position:absolute;right:7px;bottom:12px;background:#d9ff5f;color:#17180f;padding:8px 12px;border-radius:8px;font-size:9px;font-weight:700;box-shadow:0 8px 20px #0006}.card-foot{position:absolute;bottom:17px;left:21px;right:21px;font-size:8px;letter-spacing:1px;color:#85828d}.work{border-top:1px solid #ffffff18;padding-top:29px}.work-heading{display:flex;justify-content:space-between;align-items:end;margin-bottom:16px}.work-heading h2{font:600 21px 'Segoe UI',sans-serif;letter-spacing:-.7px;margin:6px 0 0}.counter{font-size:10px;color:#a5a1af}.counter i{color:#d9ff5f;font-style:normal}.builder{border:1px solid #ffffff25;border-radius:16px;background:linear-gradient(125deg,#201f29,#19191f);padding:18px 20px 16px;box-shadow:0 16px 48px #0003}.builder-head,.builder-label{display:flex;align-items:center;gap:9px}.builder-head{justify-content:space-between;margin-bottom:12px}.builder-label{font-size:11px}.muted{color:#898693}.private{font-size:9px;color:#85818e}.builder form{display:grid;grid-template-columns:1fr 1.2fr auto;align-items:end;gap:12px}.builder label{display:grid;gap:7px;font-size:10px;color:#c8c5d0}.builder input,.builder textarea{font:12px 'Segoe UI',sans-serif;resize:vertical;color:#f2eff7;background:#15151a;border:1px solid #ffffff20;border-radius:9px;padding:11px 12px;outline:none;min-height:39px}.builder input:focus,.builder textarea:focus{border-color:#d9ff5f88}.primary{height:40px;border:0;background:#d9ff5f;color:#16170e;border-radius:9px;padding:0 16px;font-size:11px;font-weight:700;cursor:pointer;white-space:nowrap}.primary:hover{background:#e5ff90}.primary span{padding-left:8px}.form-note{grid-column:1/-1;margin:0;color:#888591;font-size:9px}.form-note.success{color:#d9ff5f}.ideas{display:flex;align-items:center;gap:7px;margin-top:16px;flex-wrap:wrap}.idea-label{font-size:8px;margin-right:2px}.idea-chip{border:1px solid #ffffff20;background:#ffffff07;color:#c4c1cd;border-radius:999px;padding:7px 10px;font-size:9px;cursor:pointer}.idea-chip:hover{border-color:#d9ff5f77;color:#e4ff98}.idea-chip b{padding-left:8px;color:#d9ff5f}footer{margin-top:34px;padding:14px 0 21px;border-top:1px solid #ffffff12;display:flex;justify-content:space-between;color:#777480;font-size:9px}footer span:first-child{color:#c6c3cd}.submission-card{list-style:none;display:grid;grid-template-columns:1fr 2fr 1fr auto;gap:10px;align-items:center;border-bottom:1px solid #ffffff12;padding:10px 0}.sub-email{color:#d9ff5f;font-size:11px}.sub-idea{font-size:11px;color:#c9c5d4}.sub-date{font-size:9px;color:#888590}.delete-btn{background:transparent;border:1px solid #ffffff20;color:#888;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:10px}.delete-btn:hover{border-color:#ff6b6b;color:#ff6b6b}.empty-row{color:#777480;font-size:11px;padding:12px 0;list-style:none}@media(max-width:760px){main{padding:26px 22px 0}.top{padding:0 22px}.top nav{gap:12px}.top nav a:nth-child(n+3){display:none}.hero{grid-template-columns:1fr;gap:18px;padding:12px 0 28px}.welcome-card{height:220px}.art-window{height:120px}.builder form{grid-template-columns:1fr}.form-note{grid-column:auto}.builder-head{align-items:flex-start}.private{display:none}.hero h1{letter-spacing:-2px}footer span:last-child{display:none}.submission-card{grid-template-columns:1fr auto}}
'''


