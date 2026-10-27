"""Verified architectural patterns for hybrid code generation retrieval (RAG).

These patterns are indexed by the HybridRetriever and injected into Stage 2 prompts
to eliminate model hallucination, enforce security standards (CORS, token auth),
and maintain consistent dark-mode styling across generated projects.
"""
from __future__ import annotations

FLASK_CRUD_API_PATTERN = '''\
"""Flask CRUD REST API reference pattern."""
import argparse
import os
import sqlite3
from pathlib import Path
from flask import Flask, g, jsonify, request

app = Flask(__name__)
DB_PATH = Path(__file__).parent.parent / "data" / "app.db"
_ALLOWED_ORIGIN = os.environ.get("CORS_ORIGIN", "null")
_STUDIO_TOKEN = os.environ.get("STUDIO_TOKEN") or None

@app.before_request
def _require_token():
    if not request.path.startswith("/api/") or request.path in ("/api/health", "/health") or request.method == "OPTIONS":
        return
    if _STUDIO_TOKEN is None:
        return
    supplied = request.headers.get("X-Studio-Token", "")
    if supplied != _STUDIO_TOKEN:
        return jsonify(error="unauthorized"), 401

def _cors(response):
    if _ALLOWED_ORIGIN and _ALLOWED_ORIGIN != "null":
        response.headers["Access-Control-Allow-Origin"] = _ALLOWED_ORIGIN
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Studio-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

app.after_request(_cors)

@app.route("/api/<path:path>", methods=["OPTIONS"])
def _preflight(path):
    return app.make_default_options_response()

def _db():
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
    return g.db

@app.teardown_appcontext
def _close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.route("/api/records", methods=["GET"])
def list_records():
    rows = _db().execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/records", methods=["POST"])
def create_record():
    data = request.get_json(force=True) or {}
    cur = _db().execute("INSERT INTO items (title) VALUES (?)", (data.get("title", ""),))
    _db().commit()
    row = _db().execute("SELECT * FROM items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route("/api/records/<int:item_id>", methods=["DELETE"])
def delete_record(item_id: int):
    cur = _db().execute("DELETE FROM items WHERE id = ?", (item_id,))
    _db().commit()
    return ("", 204) if cur.rowcount > 0 else (jsonify(error="not found"), 404)

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "ok": True})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)
'''

CSS_STYLE_PATTERN = '''\
/* Dark modern design system with Segoe UI and accent #d9ff5f */
:root {
  --bg: #111116;
  --surface: #181820;
  --surface-border: #ffffff1a;
  --text-main: #f1f0f5;
  --text-muted: #85828d;
  --accent: #d9ff5f;
  --accent-ink: #17180f;
  --font-family: 'Segoe UI', system-ui, sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-family);
  background: var(--bg);
  color: var(--text-main);
  min-height: 100vh;
}
header.top {
  height: 72px;
  border-bottom: 1px solid var(--surface-border);
  display: flex;
  align-items: center;
  padding: 0 5%;
  justify-content: space-between;
}
.brand {
  font-weight: 700;
  color: #fff;
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-mark {
  width: 28px;
  height: 28px;
  background: var(--accent);
  color: var(--accent-ink);
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-weight: 800;
}
main { max-width: 1080px; margin: 0 auto; padding: 40px 24px; }
.hero { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; margin-bottom: 40px; }
.card {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: 16px;
  padding: 24px;
}
.builder form { display: grid; gap: 14px; }
input, select, textarea {
  background: #15151a;
  border: 1px solid #ffffff25;
  border-radius: 8px;
  padding: 10px 14px;
  color: #fff;
  font-family: inherit;
}
button.primary {
  background: var(--accent);
  color: var(--accent-ink);
  font-weight: 700;
  border: 0;
  border-radius: 8px;
  padding: 12px 20px;
  cursor: pointer;
}
@media (max-width: 768px) {
  .hero { grid-template-columns: 1fr; }
}
'''

JS_CLIENT_PATTERN = '''\
// Frontend client script for dynamic API interaction
document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("#idea-form");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = Object.fromEntries(new FormData(form));
      const note = document.querySelector("#form-note");
      const btn = form.querySelector("button[type='submit']");
      if (btn) btn.disabled = true;
      try {
        const res = await fetch("/api/submissions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (note) { note.textContent = "Saved successfully."; note.classList.add("success"); }
        form.reset();
      } catch (err) {
        if (note) { note.textContent = `Error: ${err.message}`; note.classList.remove("success"); }
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  const list = document.querySelector("#submissions-list");
  if (list) {
    async function loadSubmissions() {
      try {
        const res = await fetch("/api/submissions");
        if (!res.ok) throw new Error("API error");
        const items = await res.json();
        if (!items.length) {
          list.innerHTML = "<li class='empty-row'>No records found.</li>";
          return;
        }
        list.innerHTML = items.map(item => `
          <li class="submission-card">
            <span>${escapeHtml(item.title || item.name || "Record")}</span>
            <button class="delete-btn" data-id="${item.id}">✕</button>
          </li>
        `).join("");
        list.querySelectorAll(".delete-btn").forEach(btn => {
          btn.addEventListener("click", async () => {
            await fetch(`/api/submissions/${btn.dataset.id}`, { method: "DELETE" });
            loadSubmissions();
          });
        });
      } catch (err) {
        list.innerHTML = `<li class='empty-row'>Failed to load: ${err.message}</li>`;
      }
    }
    function escapeHtml(s) {
      return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    loadSubmissions();
  }
});
'''

SQL_SCHEMA_PATTERN = '''\
-- SQLite schema definition with strict typing and timestamps
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
'''

HTML_PAGE_PATTERN = '''\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>App · SketchForge</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <header class="top">
    <a class="brand" href="home.html"><span class="brand-mark">s</span>SketchForge App</a>
    <nav>
      <a href="home.html">Overview</a>
      <a href="projects.html">Records</a>
    </nav>
  </header>
  <main>
    <section class="hero">
      <div class="hero-copy">
        <h1>Dynamic Application</h1>
        <p class="lede">Generated with grounded AI and verified layouts.</p>
      </div>
      <aside class="card">
        <div class="card-art">
          <span>Active Workspace</span>
        </div>
      </aside>
    </section>
    <section class="work">
      <div class="builder">
        <form id="idea-form">
          <label>Title <input name="title" required placeholder="Enter record title"></label>
          <button class="primary" type="submit">Submit Record</button>
          <p class="form-note" id="form-note"></p>
        </form>
      </div>
    </section>
  </main>
  <script src="js/home.js"></script>
</body>
</html>
'''

PATTERN_CATALOG = [
    {"id": "flask_api", "path": "backend/api.py", "extension": ".py", "tags": "flask api backend route crud rest cors", "text": FLASK_CRUD_API_PATTERN},
    {"id": "css_style", "path": "css/style.css", "extension": ".css", "tags": "css styling dark design responsive layout grid flex", "text": CSS_STYLE_PATTERN},
    {"id": "js_client", "path": "js/home.js", "extension": ".js", "tags": "javascript js frontend fetch submit delete event api", "text": JS_CLIENT_PATTERN},
    {"id": "sql_schema", "path": "backend/schema.sql", "extension": ".sql", "tags": "sql sqlite schema table create ddl database", "text": SQL_SCHEMA_PATTERN},
    {"id": "html_page", "path": "home.html", "extension": ".html", "tags": "html page frontend responsive form nav hero card", "text": HTML_PAGE_PATTERN},
]
