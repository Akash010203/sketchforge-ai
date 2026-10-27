# ADR 0001 — Local-first desktop application, no application API

**Status:** accepted · **Date:** 2026-10-17

**Context.** The product turns sketches into designs on the user's machine. The specification
forbids FastAPI/REST/GraphQL, a local HTTP server between UI and engine, microservices, and a cloud
backend of our own.

**Decision.** One Python process. `ui/` (PySide6) → `application/AppController` → `orchestration/`
workflows → domain modules, all by direct function calls with typed objects. Long work runs on a
thread pool (`TaskManager`); results return through events (`EventBus`), which the Qt layer turns into
signals (`ui/bridge.py`). The controller imports no Qt, so the CLI, tests and GUI share one code path.

**Consequences.**
* (+) Nothing to deploy, secure or keep in sync; private by default; trivially testable headless.
* (+) The repair loop and the UI call the same renderer and evaluator.
* (−) Heavy work competes with the GUI for the GIL; mitigated by threads for I/O-bound waits and
  by keeping repairs short (hundreds of ms). A process pool can be added behind `TaskManager` if needed.
* (−) A future remote provider (NVIDIA/Nebius) is an *outbound client* only, isolated in
  `integrations/`; it must never turn into a local server.

**Alternatives rejected.** Local HTTP + web UI (adds an API surface the spec forbids); Electron
(second runtime, still needs IPC); a plugin per service (microservices).
