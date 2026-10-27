"""Full Vite + React + TypeScript Web Studio generator.

Materialises a runnable Vite+React+TypeScript project with:
  - Dynamic client-side routing via React Router v6.
  - Typed API client (fetch wrapper + auto-generated interfaces).
  - Component library built on the project spec entities and pages.
  - Optional Flask/FastAPI backend stub (reuses existing backend generators).
  - Live-preview compatible: starts via ``npm run dev``.

Entry point: :func:`generate_vite_react_project`.
"""
from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Callable

from sketchforge.generation.app_specification import AppSpec, EntitySpec, FieldSpec, PageSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48] or "new-app"


def _pascal(s: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_\s]+", s))


def _camel(s: str) -> str:
    parts = re.split(r"[-_\s]+", s)
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def _ts_type(field_type: str) -> str:
    return {
        "text": "string", "email": "string", "password": "string",
        "number": "number", "select": "string", "bool": "boolean",
        "date": "string",
    }.get(field_type, "string")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_vite_react_project(
    prompt: str,
    target: Path,
    *,
    include_backend: bool = True,
    database: str = "sqlite",
    orm: str = "sqlalchemy",
    api_target: str = "flask",
    authentication: bool = False,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Materialise a full Vite+React+TypeScript project under *target*.

    Args:
        prompt: One-sentence product brief.
        target: Parent directory; a slugified sub-directory is created inside.
        include_backend: Whether to generate a backend API stub.
        database: One of ``sqlite``, ``postgresql``, ``mysql``.
        orm: One of ``sqlalchemy``, ``dataclass``, ``prisma``.
        api_target: One of ``fastapi``, ``flask``, ``graphql``.
        authentication: Whether to include JWT auth endpoints.
        progress: Optional status callback.

    Returns:
        Absolute path to the generated project root.
    """
    def _emit(msg: str) -> None:
        if progress:
            progress(msg)

    brief = prompt.strip()
    if not brief:
        raise ValueError("Provide a brief describing what to build.")

    name = " ".join(brief.split()[:4]).strip(".,:;!\u2014-").title() or "My App"
    slug = _slug(name)
    proj_root = target.resolve() / slug
    proj_root.mkdir(parents=True, exist_ok=True)

    _emit(f"Scaffolding Vite+React+TS project: {name!r}\u2026")

    entities: list[EntitySpec] = [
        EntitySpec(
            name="Item",
            fields=[
                FieldSpec("title", "Title", "text"),
                FieldSpec("description", "Description", "text", required=False),
            ],
        )
    ]
    pages: list[PageSpec] = [
        PageSpec(name="home",      title="Home",      route="/",          description=brief),
        PageSpec(name="dashboard", title="Dashboard", route="/dashboard",  description="Your workspace"),
        PageSpec(name="about",     title="About",     route="/about",      description=f"About {name}"),
    ]
    spec = AppSpec(
        name=name,
        description=brief,
        pages=pages,
        entities=entities if include_backend else [],
        tech_frontend="react-ts",
        tech_backend="python-sqlite" if include_backend else "none",
        database=database,
        orm=orm,
        api_target=api_target,
        authentication=authentication,
        migrations=False,
    )

    files = _build_file_map(spec, name, slug, include_backend)
    for rel_path, content in files.items():
        dest_file = proj_root / rel_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(content, encoding="utf-8")
        _emit(f"  wrote {rel_path}")

    if include_backend:
        _write_backend(proj_root, spec)
        _emit("  wrote backend/")

    _emit(f"Done \u2014 {len(files)} files in {proj_root.name}/")
    return proj_root


# ---------------------------------------------------------------------------
# File map builder
# ---------------------------------------------------------------------------

def _build_file_map(
    spec: AppSpec,
    name: str,
    slug: str,
    include_backend: bool,
) -> dict[str, str]:
    files: dict[str, str] = {}

    files["package.json"]           = _package_json(slug)
    files["tsconfig.json"]          = _tsconfig()
    files["tsconfig.node.json"]     = _tsconfig_node()
    files["vite.config.ts"]         = _vite_config(include_backend)
    files["index.html"]             = _index_html(name, spec.description)
    files[".eslintrc.cjs"]          = _eslint_config()
    files[".gitignore"]             = _gitignore()
    files["README.md"]              = _readme(name, spec.description, include_backend, spec)
    files["src/main.tsx"]           = _main_tsx()
    files["src/App.tsx"]            = _app_tsx()
    files["src/router.tsx"]         = _router_tsx(spec)
    files["src/styles/global.css"]  = _global_css()
    files["src/styles/App.module.css"] = _app_module_css()
    files["src/types/api.ts"]       = _types_api(spec)
    files["src/api/client.ts"]      = _api_client(spec, include_backend)
    for page in spec.pages:
        pc = _pascal(page.name)
        files[f"src/pages/{pc}.tsx"]                = _page_component(page, spec)
        files[f"src/styles/{page.name}.module.css"] = _page_css(page)
    files["src/components/Navbar.tsx"]      = _navbar_component(spec)
    files["src/components/Sidebar.tsx"]     = _sidebar_component(spec)
    files["src/components/Card.tsx"]        = _card_component()
    files["src/components/Button.tsx"]      = _button_component()
    files["src/components/EntityTable.tsx"] = _entity_table(spec)
    files["src/components/EntityForm.tsx"]  = _entity_form(spec)
    files["src/hooks/useEntity.ts"]         = _use_entity_hook(spec, include_backend)
    return files


# ---------------------------------------------------------------------------
# Config files
# ---------------------------------------------------------------------------

def _package_json(slug: str) -> str:
    return json.dumps({
        "name": slug, "private": True, "version": "0.0.1", "type": "module",
        "scripts": {
            "dev": "vite", "build": "tsc && vite build",
            "preview": "vite preview", "lint": "eslint . --ext ts,tsx",
            "typecheck": "tsc --noEmit",
        },
        "dependencies": {
            "react": "^18.3.1", "react-dom": "^18.3.1",
            "react-router-dom": "^6.26.0",
        },
        "devDependencies": {
            "@types/react": "^18.3.1", "@types/react-dom": "^18.3.1",
            "@typescript-eslint/eslint-plugin": "^7.0.0",
            "@typescript-eslint/parser": "^7.0.0",
            "@vitejs/plugin-react": "^4.3.0",
            "eslint": "^8.57.0",
            "eslint-plugin-react-hooks": "^4.6.2",
            "eslint-plugin-react-refresh": "^0.4.9",
            "typescript": "^5.5.0", "vite": "^5.3.0",
        },
    }, indent=2) + "\n"


def _tsconfig() -> str:
    return json.dumps({
        "compilerOptions": {
            "target": "ES2020", "useDefineForClassFields": True,
            "lib": ["ES2020", "DOM", "DOM.Iterable"], "module": "ESNext",
            "skipLibCheck": True, "moduleResolution": "bundler",
            "allowImportingTsExtensions": True, "resolveJsonModule": True,
            "isolatedModules": True, "noEmit": True, "jsx": "react-jsx",
            "strict": True, "noUnusedLocals": True, "noUnusedParameters": True,
            "noFallthroughCasesInSwitch": True, "paths": {"@/*": ["./src/*"]},
        },
        "include": ["src"],
        "references": [{"path": "./tsconfig.node.json"}],
    }, indent=2) + "\n"


def _tsconfig_node() -> str:
    return json.dumps({
        "compilerOptions": {
            "composite": True, "skipLibCheck": True, "module": "ESNext",
            "moduleResolution": "bundler", "allowSyntheticDefaultImports": True,
            "strict": True,
        },
        "include": ["vite.config.ts"],
    }, indent=2) + "\n"


def _vite_config(include_backend: bool) -> str:
    proxy = (
        "\n  server: {\n    proxy: {\n      '/api': {\n        target: 'http://127.0.0.1:5000',\n"
        "        changeOrigin: true,\n        secure: false,\n      },\n    },\n  },"
        if include_backend else ""
    )
    return (
        "import { defineConfig } from 'vite'\n"
        "import react from '@vitejs/plugin-react'\n"
        "import { resolve } from 'path'\n\n"
        "export default defineConfig({\n"
        "  plugins: [react()],\n"
        "  resolve: { alias: { '@': resolve(__dirname, './src') } },"
        f"{proxy}\n"
        "})\n"
    )


def _eslint_config() -> str:
    return (
        "module.exports = {\n  root: true,\n  env: { browser: true, es2020: true },\n"
        "  extends: ['eslint:recommended','plugin:@typescript-eslint/recommended','plugin:react-hooks/recommended'],\n"
        "  ignorePatterns: ['dist', '.eslintrc.cjs'],\n  parser: '@typescript-eslint/parser',\n"
        "  plugins: ['react-refresh'],\n"
        "  rules: { 'react-refresh/only-export-components': ['warn', { allowConstantExport: true }] },\n}\n"
    )


def _gitignore() -> str:
    return "node_modules/\ndist/\n.env\n.env.local\n*.local\n__pycache__/\n*.py[cod]\n.venv/\n"


def _index_html(name: str, description: str) -> str:
    return (
        "<!doctype html>\n<html lang=\"en\">\n  <head>\n"
        "    <meta charset=\"UTF-8\" />\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
        f"    <meta name=\"description\" content=\"{description}\" />\n"
        "    <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />\n"
        "    <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap\" rel=\"stylesheet\" />\n"
        f"    <title>{name}</title>\n  </head>\n  <body>\n"
        "    <div id=\"root\"></div>\n    <script type=\"module\" src=\"/src/main.tsx\"></script>\n  </body>\n</html>\n"
    )


def _readme(name: str, description: str, include_backend: bool, spec: AppSpec) -> str:
    backend_section = (
        f"\n## Backend\n\nUses **{spec.api_target}** + **{spec.orm}** + **{spec.database}**.\n\n"
        "```bash\ncd backend && pip install -r ../requirements.txt && python -m backend.api\n```\n"
        if include_backend else ""
    )
    return (
        f"# {name}\n\n> {description}\n\nGenerated by **SketchForge Studio** (Vite+React+TypeScript)\n\n"
        "## Quick Start\n\n```bash\nnpm install\nnpm run dev\n```\n\nOpen <http://localhost:5173>\n"
        f"{backend_section}"
        "\n## Scripts\n\n| Script | Description |\n|--------|-------------|\n"
        "| `npm run dev` | Vite dev server with HMR |\n"
        "| `npm run build` | Type-check + production bundle |\n"
        "| `npm run typecheck` | TypeScript only |\n"
        "| `npm run lint` | ESLint |\n"
    )


# ---------------------------------------------------------------------------
# React source
# ---------------------------------------------------------------------------

def _main_tsx() -> str:
    return (
        "import React from 'react'\nimport ReactDOM from 'react-dom/client'\n"
        "import App from './App'\nimport './styles/global.css'\n\n"
        "ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(\n"
        "  <React.StrictMode>\n    <App />\n  </React.StrictMode>,\n)\n"
    )


def _app_tsx() -> str:
    return (
        "import { RouterProvider } from 'react-router-dom'\nimport { router } from './router'\n"
        "import styles from './styles/App.module.css'\n\n"
        "export default function App() {\n"
        "  return (\n    <div className={styles.root}>\n      <RouterProvider router={router} />\n    </div>\n  )\n}\n"
    )


def _router_tsx(spec: AppSpec) -> str:
    imports = "\n".join(
        f"import {_pascal(p.name)} from './pages/{_pascal(p.name)}'"
        for p in spec.pages
    )
    routes = "\n      ".join(
        f"{{ path: '{p.route}', element: <{_pascal(p.name)} /> }},"
        for p in spec.pages
    )
    return (
        "import { createBrowserRouter } from 'react-router-dom'\n"
        f"{imports}\n\n"
        "export const router = createBrowserRouter([\n  {\n    path: '/',\n    children: [\n"
        f"      {routes}\n    ],\n  }},\n])\n"
    )


def _types_api(spec: AppSpec) -> str:
    lines = ["// Auto-generated TypeScript interfaces\n"]
    for entity in spec.entities:
        lines.append(f"export interface {entity.name} {{")
        lines.append("  id: number;")
        for f in entity.fields:
            opt = "" if f.required else "?"
            lines.append(f"  {f.name}{opt}: {_ts_type(f.type)};")
        lines += ["  created_at?: string;", "  updated_at?: string;", "}\n"]
        lines.append(f"export type {entity.name}Create = Omit<{entity.name}, 'id' | 'created_at' | 'updated_at'>;\n")
    lines += ["export interface ApiError {", "  error: string;", "}\n"]
    return "\n".join(lines)


def _api_client(spec: AppSpec, include_backend: bool) -> str:
    if not include_backend or not spec.entities:
        return "// No backend configured\nexport const BASE_URL = '';\n"
    e = spec.entities[0]
    route = e.name.lower() + "s"
    n, c = e.name, _camel(e.name)
    return (
        f"import type {{ {n}, {n}Create, ApiError }} from '../types/api';\n\n"
        "const BASE_URL = import.meta.env.VITE_API_URL ?? '';\n"
        "const STUDIO_TOKEN = import.meta.env.VITE_STUDIO_TOKEN ?? '';\n\n"
        "async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {\n"
        "  const res = await fetch(`${BASE_URL}${path}`, {\n    ...init,\n"
        "    headers: {\n      'Content-Type': 'application/json',\n"
        "      ...(STUDIO_TOKEN ? { 'X-Studio-Token': STUDIO_TOKEN } : {}),\n"
        "      ...(init.headers ?? {}),\n    },\n  });\n"
        "  if (!res.ok) {\n"
        "    const err: ApiError = await res.json().catch(() => ({ error: res.statusText }));\n"
        "    throw new Error(err.error ?? `HTTP ${res.status}`);\n  }\n"
        "  if (res.status === 204) return undefined as T;\n  return res.json();\n}\n\n"
        f"export const {c}Api = {{\n"
        f"  list:   ()                      => apiFetch<{n}[]>('/api/{route}'),\n"
        f"  get:    (id: number)            => apiFetch<{n}>(`/api/{route}/${{id}}`),\n"
        f"  create: (data: {n}Create)       => apiFetch<{n}>('/api/{route}', {{ method: 'POST', body: JSON.stringify(data) }}),\n"
        f"  update: (id: number, data: Partial<{n}Create>) =>\n"
        f"    apiFetch<{n}>(`/api/{route}/${{id}}`, {{ method: 'PUT', body: JSON.stringify(data) }}),\n"
        f"  remove: (id: number)            => apiFetch<void>(`/api/{route}/${{id}}`, {{ method: 'DELETE' }}),\n"
        "};\n"
    )


def _use_entity_hook(spec: AppSpec, include_backend: bool) -> str:
    if not include_backend or not spec.entities:
        return "// No entities configured\nexport {};\n"
    e = spec.entities[0]
    n, c = e.name, _camel(e.name)
    return (
        "import { useState, useEffect, useCallback } from 'react';\n"
        f"import {{ {c}Api }} from '../api/client';\n"
        f"import type {{ {n}, {n}Create }} from '../types/api';\n\n"
        f"export function use{n}s() {{\n"
        f"  const [items, setItems]     = useState<{n}[]>([]);\n"
        "  const [loading, setLoading] = useState(false);\n"
        "  const [error, setError]     = useState<string | null>(null);\n\n"
        "  const refresh = useCallback(async () => {\n"
        "    setLoading(true); setError(null);\n"
        f"    try {{ setItems(await {c}Api.list()); }}\n"
        "    catch (e) { setError(e instanceof Error ? e.message : 'Unknown error'); }\n"
        "    finally { setLoading(false); }\n  }, []);\n\n"
        "  useEffect(() => { refresh(); }, [refresh]);\n\n"
        f"  const create = async (data: {n}Create) => {{ await {c}Api.create(data); await refresh(); }};\n"
        f"  const remove = async (id: number)      => {{ await {c}Api.remove(id);   await refresh(); }};\n\n"
        "  return { items, loading, error, refresh, create, remove };\n}\n"
    )


# ---------------------------------------------------------------------------
# Page components
# ---------------------------------------------------------------------------

def _page_component(page: PageSpec, spec: AppSpec) -> str:
    pc = _pascal(page.name)
    is_dash = page.name == "dashboard"
    entity_import = entity_vars = entity_jsx = ""
    if is_dash and spec.entities:
        n = spec.entities[0].name
        entity_import = f"import {{ use{n}s }} from '../hooks/useEntity';\nimport EntityTable from '../components/EntityTable';\nimport EntityForm from '../components/EntityForm';\n"
        entity_vars = f"  const {{ items, loading, error, create, remove }} = use{n}s();\n"
        entity_jsx = (
            "\n          <section className={styles.section}>\n"
            f"            <h2 className={{styles.sectionTitle}}>Your {n}s</h2>\n"
            "            <EntityForm onCreate={create} />\n"
            "            {loading && <p className={styles.loading}>Loading\u2026</p>}\n"
            "            {error   && <p className={styles.error}>Error: {error}</p>}\n"
            "            <EntityTable items={items} onDelete={remove} />\n"
            "          </section>"
        )
    return (
        f"import Navbar from '../components/Navbar';\n"
        f"import Sidebar from '../components/Sidebar';\n"
        f"{entity_import}"
        f"import styles from '../styles/{page.name}.module.css';\n\n"
        f"export default function {pc}() {{\n"
        f"{entity_vars}"
        "  return (\n    <div className={styles.layout}>\n      <Sidebar />\n"
        "      <div className={styles.main}>\n        <Navbar />\n"
        "        <div className={styles.content}>\n          <header className={styles.hero}>\n"
        f"            <h1 className={{styles.title}}>{page.title}</h1>\n"
        f"            <p className={{styles.description}}>{page.description}</p>\n"
        f"          </header>{entity_jsx}\n"
        "        </div>\n      </div>\n    </div>\n  );\n}\n"
    )


def _page_css(page: PageSpec) -> str:
    return (
        f"/* {page.name}.module.css */\n"
        ".layout { display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }\n"
        ".main { display: flex; flex-direction: column; }\n"
        ".content { padding: 2rem 2.5rem; flex: 1; }\n"
        ".hero { margin-bottom: 2rem; }\n"
        ".title { font-size: clamp(1.6rem,3vw,2.4rem); font-weight: 700; letter-spacing: -.04em; margin: 0 0 .5rem; color: var(--fg); }\n"
        ".description { color: var(--muted); font-size: .95rem; max-width: 540px; }\n"
        ".section { margin-top: 1.5rem; }\n"
        ".sectionTitle { font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; }\n"
        ".loading { color: var(--accent); font-size: .85rem; }\n"
        ".error { color: #ff6b6b; font-size: .85rem; }\n"
        "@media (max-width: 768px) { .layout { grid-template-columns: 1fr; } }\n"
    )


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------

def _navbar_component(spec: AppSpec) -> str:
    return (
        "import { Link } from 'react-router-dom';\nimport styles from '../styles/App.module.css';\n\n"
        "export default function Navbar() {\n  return (\n    <header className={styles.navbar}>\n"
        f"      <span className={{styles.navBrand}}>{spec.name}</span>\n"
        "      <nav className={styles.navLinks}>\n"
        + "".join(f"        <Link to=\"{p.route}\">{p.title}</Link>\n" for p in spec.pages)
        + "      </nav>\n      <button className={styles.navAvatar} aria-label=\"Account\">A</button>\n"
        "    </header>\n  );\n}\n"
    )


def _sidebar_component(spec: AppSpec) -> str:
    links = "".join(f"        <a href=\"{p.route}\" className={{styles.sideLink}}>{p.title}</a>\n" for p in spec.pages)
    return (
        "import styles from '../styles/App.module.css';\n\n"
        "export default function Sidebar() {\n  return (\n    <aside className={styles.sidebar}>\n"
        "      <div className={styles.sideBrand}>\n"
        f"        <span className={{styles.sideMark}}>s</span>\n        <span>{spec.name}</span>\n      </div>\n"
        "      <nav className={styles.sideNav}>\n"
        f"{links}      </nav>\n    </aside>\n  );\n}}\n"
    )


def _card_component() -> str:
    return (
        "import styles from '../styles/App.module.css';\n\n"
        "interface CardProps { title?: string; children: React.ReactNode; className?: string; }\n\n"
        "export default function Card({ title, children, className = '' }: CardProps) {\n"
        "  return (\n    <div className={`${styles.card} ${className}`}>\n"
        "      {title && <h3 className={styles.cardTitle}>{title}</h3>}\n"
        "      {children}\n    </div>\n  );\n}\n"
    )


def _button_component() -> str:
    return (
        "import styles from '../styles/App.module.css';\n\n"
        "interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {\n"
        "  variant?: 'primary' | 'ghost' | 'danger';\n  size?: 'sm' | 'md' | 'lg';\n}\n\n"
        "export default function Button({ variant = 'primary', size = 'md', className = '', ...props }: ButtonProps) {\n"
        "  return <button className={`${styles.btn} ${styles[`btn-${variant}`]} ${styles[`btn-${size}`]} ${className}`} {...props} />;\n}\n"
    )


def _entity_table(spec: AppSpec) -> str:
    if not spec.entities:
        return "export default function EntityTable() { return null; }\n"
    e = spec.entities[0]
    headers = "".join(f"<th>{f.label}</th>" for f in e.fields)
    cells = "".join(f"<td>{{String(item.{f.name} ?? '')}}</td>" for f in e.fields)
    n = e.name
    return (
        f"import type {{ {n} }} from '../types/api';\nimport styles from '../styles/App.module.css';\n\n"
        f"interface Props {{ items: {n}[]; onDelete?: (id: number) => void; }}\n\n"
        f"export default function EntityTable({{ items, onDelete }}: Props) {{\n"
        "  if (!items.length) return <p className={styles.empty}>No items yet.</p>;\n"
        "  return (\n    <div className={styles.tableWrap}>\n      <table className={styles.table}>\n"
        f"        <thead><tr><th>#</th>{headers}{{onDelete && <th></th>}}</tr></thead>\n"
        "        <tbody>\n          {items.map(item => (\n            <tr key={item.id}>\n"
        f"              <td>{{item.id}}</td>{cells}\n"
        "              {onDelete && <td><button className={styles.deleteBtn} onClick={() => onDelete(item.id)}>&#x2715;</button></td>}\n"
        "            </tr>\n          ))}\n        </tbody>\n      </table>\n    </div>\n  );\n}\n"
    )


def _entity_form(spec: AppSpec) -> str:
    if not spec.entities:
        return "export default function EntityForm() { return null; }\n"
    e = spec.entities[0]
    n, c = e.name, _camel(e.name)
    initial = "{ " + ", ".join(f"{f.name}: ''" for f in e.fields) + " }"
    inputs = "".join(
        f"        <label className={{styles.label}}>{f.label}"
        f"<input className={{styles.input}} name=\"{f.name}\" type=\"text\" "
        f"value={{form.{f.name} as string}} onChange={{onChange}} "
        f"placeholder=\"{f.label}\" {'required' if f.required else ''} /></label>\n"
        for f in e.fields
    )
    return (
        "import { useState, type ChangeEvent, type FormEvent } from 'react';\n"
        f"import type {{ {n}Create }} from '../types/api';\nimport styles from '../styles/App.module.css';\n\n"
        f"interface Props {{ onCreate: (data: {n}Create) => Promise<void>; }}\n\n"
        f"export default function EntityForm({{ onCreate }}: Props) {{\n"
        f"  const [form, setForm] = useState<Record<string, unknown>>({initial});\n"
        "  const [busy, setBusy] = useState(false);\n"
        "  const onChange = (e: ChangeEvent<HTMLInputElement>) =>\n"
        "    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }));\n"
        "  const onSubmit = async (e: FormEvent) => {\n    e.preventDefault(); setBusy(true);\n"
        f"    try {{ await onCreate(form as unknown as {n}Create); setForm({initial}); }}\n"
        "    finally { setBusy(false); }\n  };\n"
        "  return (\n    <form className={styles.form} onSubmit={onSubmit}>\n"
        f"{inputs}"
        f"      <button className={{styles.submitBtn}} type=\"submit\" disabled={{busy}}>{{busy ? 'Saving\u2026' : 'Add {n}'}}</button>\n"
        "    </form>\n  );\n}\n"
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _global_css() -> str:
    return (
        "/* Global design tokens */\n"
        "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');\n\n"
        ":root {\n  --bg: #111116;\n  --bg2: #1a1a22;\n  --bg3: #22212e;\n"
        "  --fg: #f2eff7;\n  --muted: #a09db0;\n  --accent: #d9ff5f;\n  --accent-fg: #16170e;\n"
        "  --border: rgba(255,255,255,.1);\n  --radius: 10px;\n  --shadow: 0 8px 32px rgba(0,0,0,.35);\n"
        "  font-family: 'Inter', system-ui, sans-serif;\n  font-synthesis: none;\n"
        "  text-rendering: optimizeLegibility;\n  -webkit-font-smoothing: antialiased;\n}\n"
        "*, *::before, *::after { box-sizing: border-box; }\n* { margin: 0; padding: 0; }\n"
        "body {\n  background: radial-gradient(ellipse 70% 40% at 80% 0%, #29243a, transparent 70%),\n"
        "              radial-gradient(ellipse 50% 35% at 5% 85%, #191b28, transparent 65%), var(--bg);\n"
        "  color: var(--fg);\n  min-height: 100vh;\n}\n"
        "a { color: var(--accent); text-decoration: none; }\na:hover { text-decoration: underline; }\n"
        "h1,h2,h3,h4 { letter-spacing: -.03em; }\n"
        "button { font: inherit; cursor: pointer; }\n"
        "input,textarea,select { font: inherit; color: var(--fg); background: var(--bg2); "
        "border: 1px solid var(--border); border-radius: var(--radius); padding: .5rem .75rem; "
        "outline: none; width: 100%; }\n"
        "input:focus,textarea:focus { border-color: var(--accent); }\n"
    )


def _app_module_css() -> str:
    return (
        "/* App.module.css - layout primitives */\n\n"
        ".sidebar { background: var(--bg2); border-right: 1px solid var(--border); padding: 1.25rem 1rem; "
        "display: flex; flex-direction: column; gap: 2rem; position: sticky; top: 0; height: 100vh; overflow-y: auto; }\n"
        ".sideBrand { display: flex; align-items: center; gap: .6rem; font-weight: 700; font-size: .95rem; }\n"
        ".sideMark { width: 28px; height: 28px; border-radius: 8px; background: var(--accent); color: var(--accent-fg); "
        "display: grid; place-items: center; font-size: 1rem; font-weight: 900; flex-shrink: 0; }\n"
        ".sideNav { display: flex; flex-direction: column; gap: .25rem; }\n"
        ".sideLink { display: block; padding: .5rem .75rem; border-radius: 8px; font-size: .875rem; color: var(--muted); transition: background .15s,color .15s; }\n"
        ".sideLink:hover { background: rgba(255,255,255,.06); color: var(--fg); text-decoration: none; }\n"
        ".navbar { height: 60px; border-bottom: 1px solid var(--border); display: flex; align-items: center; "
        "padding: 0 2rem; gap: 2rem; background: rgba(17,17,22,.8); backdrop-filter: blur(12px); "
        "position: sticky; top: 0; z-index: 10; }\n"
        ".navBrand { font-weight: 700; font-size: .95rem; }\n"
        ".navLinks { display: flex; gap: 1.5rem; font-size: .875rem; margin: auto; color: var(--muted); }\n"
        ".navLinks a { color: inherit; }\n.navLinks a:hover { color: var(--fg); text-decoration: none; }\n"
        ".navAvatar { width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--border); background: var(--bg3); color: var(--fg); }\n"
        ".root { min-height: 100vh; }\n"
        ".card { background: var(--bg2); border: 1px solid var(--border); border-radius: 14px; padding: 1.25rem 1.5rem; box-shadow: var(--shadow); }\n"
        ".cardTitle { font-size: 1rem; font-weight: 600; margin-bottom: .75rem; }\n"
        ".btn { border: 0; border-radius: 8px; padding: .5rem 1.1rem; font-size: .875rem; font-weight: 600; transition: opacity .15s; }\n"
        ".btn:hover { opacity: .85; }\n"
        ".btn-primary { background: var(--accent); color: var(--accent-fg); }\n"
        ".btn-ghost { background: rgba(255,255,255,.06); color: var(--fg); border: 1px solid var(--border); }\n"
        ".btn-danger { background: #ff4f4f; color: #fff; }\n"
        ".btn-sm { padding: .3rem .7rem; font-size: .8rem; }\n.btn-md { padding: .5rem 1.1rem; }\n.btn-lg { padding: .7rem 1.5rem; font-size: 1rem; }\n"
        ".tableWrap { overflow-x: auto; }\n"
        ".table { width: 100%; border-collapse: collapse; font-size: .875rem; }\n"
        ".table th { text-align: left; padding: .5rem .75rem; color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: .75rem; letter-spacing: .08em; text-transform: uppercase; }\n"
        ".table td { padding: .65rem .75rem; border-bottom: 1px solid rgba(255,255,255,.05); }\n"
        ".table tr:hover td { background: rgba(255,255,255,.03); }\n"
        ".empty { color: var(--muted); font-size: .875rem; padding: 1rem 0; }\n"
        ".deleteBtn { background: transparent; border: 1px solid var(--border); color: var(--muted); border-radius: 6px; padding: .2rem .5rem; font-size: .75rem; transition: border-color .15s,color .15s; }\n"
        ".deleteBtn:hover { border-color: #ff4f4f; color: #ff4f4f; }\n"
        ".form { display: flex; flex-direction: column; gap: .75rem; max-width: 480px; }\n"
        ".label { display: flex; flex-direction: column; gap: .35rem; font-size: .8rem; color: var(--muted); }\n"
        ".input { font-size: .875rem; }\n"
        ".submitBtn { height: 38px; border: 0; border-radius: 8px; background: var(--accent); color: var(--accent-fg); font-weight: 700; font-size: .875rem; transition: opacity .15s; }\n"
        ".submitBtn:hover { opacity: .85; }\n.submitBtn:disabled { opacity: .5; cursor: not-allowed; }\n"
        "@media (max-width: 768px) { .navbar { padding: 0 1rem; } .navLinks a:nth-child(n+3) { display: none; } }\n"
    )


# ---------------------------------------------------------------------------
# Backend stub writer
# ---------------------------------------------------------------------------

def _write_backend(root: Path, spec: AppSpec) -> None:
    """Delegate backend file generation to the existing backend generators."""
    from sketchforge.generation.backend.schema_generator import render_backend_file, _requirements
    from sketchforge.generation.project_planner import plan_react_ts

    plan = plan_react_ts(spec)
    for pf in plan.files:
        if not pf.generator.startswith("backend_"):
            continue
        content = render_backend_file(pf, plan)
        dest = root / pf.relative_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    req_files = [f for f in plan.files if f.generator == "backend_requirements"]
    if not req_files and spec.orm != "prisma":
        (root / "requirements.txt").write_text(_requirements(spec), encoding="utf-8")
