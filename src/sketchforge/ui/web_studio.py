"""Local browser studio for generating and previewing complete SketchForge apps."""

from __future__ import annotations

import json
import logging
import mimetypes
import io
import threading
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from sketchforge.utilities.paths import repo_root

log = logging.getLogger(__name__)
_JOBS: dict[str, dict] = {}
_PROJECTS: dict[str, Path] = {}
_PREVIEWS: dict[str, str] = {}
# Keep canonical Design IR server-side; the browser only holds an opaque analysis id.
_ANALYSES: dict[str, tuple[object, dict]] = {}
_PREVIEW_SERVERS: list[ThreadingHTTPServer] = []
_BACKENDS: list[object] = []
_LOCK = threading.Lock()
# Tracks the job_id of the currently running generation/revision job.
# Only one job may run at a time; a second submit is rejected with 409.
_ACTIVE_JOB: str | None = None
_WEB_ROOT = Path(__file__).with_name("web_studio")


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "SketchForgeStudio/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/studio"}:
            self._static(_WEB_ROOT / "index.html")
        elif parsed.path.startswith("/assets/"):
            name = Path(unquote(parsed.path.removeprefix("/assets/"))).name
            self._static(_WEB_ROOT / name)
        elif parsed.path == "/api/projects":
            with _LOCK:
                projects = [{"name": p.name, "slug": slug} for slug, p in _PROJECTS.items()]
            self._json(200, projects)
        elif parsed.path.startswith("/api/export/"):
            slug = unquote(parsed.path.removeprefix("/api/export/"))
            with _LOCK:
                root = _PROJECTS.get(slug)
            if root is None or not root.is_dir():
                self._json(404, {"error": "Project not found."})
                return
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for file in sorted(root.rglob("*")):
                    if file.is_file() and not any(part.startswith(".") for part in file.relative_to(root).parts):
                        bundle.write(file, file.relative_to(root).as_posix())
            payload = archive.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{root.name}.zip"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with _LOCK:
                job = dict(_JOBS.get(job_id) or {})
            if not job:
                self._json(404, {"error": "Job not found"})
                return
            # Merge richer data from the HybridOrchestrator job if available
            try:
                from sketchforge.orchestration.hybrid_orchestrator import get_hybrid_orchestrator
                hjob = get_hybrid_orchestrator().get_job(job_id)
                if hjob:
                    hjob_dict = hjob.to_dict()
                    # Merge: the local _JOBS dict may have cancel Event that we must not serialise
                    job.pop("cancel", None)
                    job.update({
                        "verification_status": hjob_dict.get("verification_status", "skipped"),
                        "history": hjob_dict.get("history", []),
                        "discrepancy": hjob_dict.get("discrepancy"),
                    })
                    # Read generation_type from the .sketchforge_meta.json if project is ready
                    if hjob.project_root and hjob.project_root.is_dir():
                        try:
                            meta_file = hjob.project_root / ".sketchforge_meta.json"
                            if meta_file.exists():
                                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                                job["generation_type"] = meta.get("generation", "template")
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                pass
            # Remove non-serialisable Event
            job.pop("cancel", None)
            self._json(200, job)
        elif parsed.path.startswith("/api/design-ir/"):
            # Expose sketch analysis results for the browser inspector panel.
            slug = unquote(parsed.path.removeprefix("/api/design-ir/"))
            try:
                from sketchforge.orchestration.hybrid_orchestrator import get_hybrid_orchestrator
                # Find the job whose project matches this slug
                hjob = next(
                    (j for j in get_hybrid_orchestrator()._jobs.values() if j.project_slug == slug),
                    None,
                )
                if hjob is None or hjob.design_doc is None:
                    self._json(404, {"error": "No sketch analysis available for this project."})
                    return
                # Build a serialisable representation
                doc = hjob.design_doc
                components = []
                for comp in getattr(doc, "components", []):
                    try:
                        bbox = comp.bbox
                        components.append({
                            "id": comp.id,
                            "type": comp.type.value if hasattr(comp.type, "value") else str(comp.type),
                            "label": getattr(comp, "label", "") or "",
                            "bbox": {"x": bbox.x, "y": bbox.y, "w": bbox.w, "h": bbox.h},
                            "parent_id": getattr(comp, "parent_id", None),
                        })
                    except Exception:  # noqa: BLE001
                        pass
                self._json(200, {
                    "slug": slug,
                    "component_count": len(components),
                    "components": components,
                    "layout_block": hjob.layout_block,
                })
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
        elif parsed.path.startswith("/preview/"):
            self._serve_preview(parsed.path)
        elif parsed.path.startswith("/api/project-api/"):
            self._proxy_api("GET", slug=unquote(parsed.path.split("/", 3)[3]), api_path=parsed.query)
        elif parsed.path.startswith("/api/"):
            self._proxy_api("GET")
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/upload/"):
            slug = unquote(urlparse(self.path).path.rsplit("/", 1)[-1])
            with _LOCK:
                root = _PROJECTS.get(slug)
            if root is None:
                self._json(404, {"error": "Generate or open a project before adding an image."})
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
            extension = {
                "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
                "video/mp4": ".mp4", "video/webm": ".webm", "video/ogg": ".ogv",
            }.get(content_type)
            length = int(self.headers.get("Content-Length", 0))
            limit = 50 * 1024 * 1024 if extension in {".mp4", ".webm", ".ogv"} else 10 * 1024 * 1024
            if extension is None or length < 1 or length > limit:
                self._json(400, {"error": "Choose a PNG, JPEG, WebP, or GIF image under 10 MB, or MP4/WebM video under 50 MB."})
                return
            data = self.rfile.read(length)
            if len(data) != length:
                self._json(400, {"error": "Image upload was incomplete."})
                return
            upload = root / "assets" / "uploads" / f"{uuid.uuid4().hex}{extension}"
            upload.parent.mkdir(parents=True, exist_ok=True)
            upload.write_bytes(data)
            self._json(201, {"url": f"/assets/uploads/{upload.name}"})
        elif self.path == "/api/sketch-analysis":
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
            extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/bmp": ".bmp", "image/tiff": ".tif"}.get(content_type)
            length = int(self.headers.get("Content-Length", 0))
            if extension is None or length < 1 or length > 10 * 1024 * 1024:
                self._json(400, {"error": "Choose a PNG, JPEG, WebP, BMP, or TIFF sketch under 10 MB."})
                return
            data = self.rfile.read(length)
            if len(data) != length:
                self._json(400, {"error": "Sketch upload was incomplete."})
                return
            try:
                from sketchforge.vision import analyze, load_image_bytes
                from sketchforge.vision.to_design_ir import (
                    build_nemotron_layout_block,
                    vision_result_to_document,
                )

                loaded = load_image_bytes(data, f"sketch{extension}")
                result = analyze(loaded)
                width, height = loaded.width, loaded.height

                # Legacy plain-text regions (kept for backward compat with studio.js)
                observations = []
                regions: list[dict] = []
                for detection in sorted(result.detections, key=lambda item: (item.bbox[1], item.bbox[0]))[:20]:
                    x, y, w, h = detection.bbox
                    x_pct = round(x / width * 100, 1)
                    y_pct = round(y / height * 100, 1)
                    w_pct = round(w / width * 100, 1)
                    h_pct = round(h / height * 100, 1)
                    observations.append(
                        f"{detection.type} at ({x_pct}%, {y_pct}%), "
                        f"about {w_pct}% wide by {h_pct}% tall"
                    )
                    regions.append({
                        "type": detection.type,
                        "x": x_pct,
                        "y": y_pct,
                        "w": w_pct,
                        "h": h_pct,
                    })
                if not observations:
                    observations = ["No distinct UI regions were detected; use the sketch as a loose visual guide."]
                layout = "\n".join(f"- {item}" for item in observations)

                # NEW: structured layout block for the Nemotron Stage-1 prompt.
                # Converts VisionResult -> DesignDocument -> AppSpec, packages
                # exact design-pixel bboxes, containment hierarchy, and heuristic
                # AppSpec so the AI follows the sketch geometry precisely.
                sketch_name = f"sketch{extension}"
                try:
                    layout_block = build_nemotron_layout_block(result, sketch_name=sketch_name)
                    design_doc = vision_result_to_document(result, sketch_name=sketch_name)
                except Exception as ir_exc:  # noqa: BLE001
                    log.warning("Could not build Design IR from sketch: %s", ir_exc)
                    layout_block = None
                    design_doc = None

                analysis_id = None
                if layout_block is not None and design_doc is not None:
                    analysis_id = uuid.uuid4().hex
                    with _LOCK:
                        _ANALYSES[analysis_id] = (design_doc, layout_block)

                n_components = len(layout_block.get("components", [])) if layout_block else 0
                self._json(200, {
                    "width": width, "height": height,
                    "count": len(result.detections),
                    # Legacy fields preserved for studio.js frontend
                    "layout": layout,
                    "regions": regions,
                    "analysis_id": analysis_id,
                    # Structured fields consumed by the Nemotron generation pipeline
                    "layout_block": layout_block,
                    "summary": (
                        f"Analyzed sketch ({width}×{height}); "
                        f"detected {len(result.detections)} UI region(s)"
                        + (f", mapped to {n_components} design component(s)." if n_components else ".")
                    ),
                })
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"error": f"Could not analyze sketch: {exc}"})
        elif self.path == "/api/generate" or self.path.startswith("/api/revise/"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                prompt = str(data.get("prompt", "")).strip()
                if not prompt:
                    self._json(400, {"error": "Describe the app you want to create."})
                    return
                job_id = uuid.uuid4().hex[:12]
                cancel_event = threading.Event()
                from sketchforge.orchestration.hybrid_orchestrator import get_hybrid_orchestrator
                analysis_id = str(data.get("analysis_id", "")).strip()
                design_doc = layout_block = None
                if analysis_id:
                    with _LOCK:
                        analysis = _ANALYSES.get(analysis_id)
                    if analysis is None:
                        self._json(400, {"error": "Sketch analysis expired. Upload the sketch again."})
                        return
                    design_doc, layout_block = analysis
                hjob = get_hybrid_orchestrator().create_job(
                    prompt, design_doc=design_doc, job_id=job_id,
                )
                hjob.layout_block = layout_block
                with _LOCK:
                    global _ACTIVE_JOB
                    if _ACTIVE_JOB is not None:
                        active_id = _ACTIVE_JOB
                        self._json(409, {
                            "error": "A generation job is already running.",
                            "active_job_id": active_id,
                        })
                        return
                    _ACTIVE_JOB = job_id
                    _JOBS[job_id] = {
                        "status": "running",
                        "progress": "Starting generation…",
                        "cancel": cancel_event,
                        "state": hjob.state.value,
                        "options": {
                            "database": str(data.get("database", "sqlite")).lower(),
                            "orm": str(data.get("orm", "dataclass")).lower(),
                            "api_target": str(data.get("api_target", "flask")).lower(),
                            "authentication": bool(data.get("authentication", False)),
                            "migrations": bool(data.get("migrations", False)),
                        },
                    }
                if self.path.startswith("/api/revise/"):
                    slug = unquote(self.path.rsplit("/", 1)[-1])
                    threading.Thread(
                        target=self._revise,
                        args=(job_id, slug, prompt, cancel_event),
                        daemon=True,
                        name=f"sketchforge-revise-{job_id}",
                    ).start()
                else:
                    threading.Thread(
                        target=self._generate,
                        args=(job_id, prompt, cancel_event),
                        daemon=True,
                        name=f"sketchforge-generate-{job_id}",
                    ).start()
                self._json(202, {"id": job_id})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json(400, {"error": f"Invalid request: {exc}"})
        elif self.path.startswith("/api/nl-edit/"):
            # Natural-language design edit for an existing generated project.
            # Uses the existing local_parser and model_planner (the same logic as the desktop
            # "Ask SketchForge" bar) but applied to the generated project via ai_revise_project.
            slug = unquote(self.path.removeprefix("/api/nl-edit/"))
            with _LOCK:
                root = _PROJECTS.get(slug)
            if root is None:
                self._json(404, {"error": "Project not found. Generate a project first."})
                return
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                instruction = str(data.get("instruction", "")).strip()
                if not instruction:
                    self._json(400, {"error": "Provide an instruction, e.g. 'Change the primary color to blue'."})
                    return
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json(400, {"error": f"Invalid request: {exc}"})
                return
            try:
                from sketchforge.generation.ai_generator import ai_revise_project
                updated = ai_revise_project(root, instruction, progress=lambda m: log.info("nl-edit: %s", m))
                if not updated:
                    self._json(422, {"error": "The AI revision did not produce any file changes. Check model configuration."})
                    return
                self._json(200, {"applied": True, "slug": slug, "instruction": instruction})
            except Exception as exc:  # noqa: BLE001
                log.exception("NL edit failed")
                self._json(500, {"error": str(exc)})
        elif self.path.startswith("/api/"):
            self._proxy_api("POST")
        else:
            self.send_error(404)

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path.startswith("/api/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            from sketchforge.orchestration.hybrid_orchestrator import get_hybrid_orchestrator
            get_hybrid_orchestrator().cancel_job(job_id)
            with _LOCK:
                job = _JOBS.get(job_id)
            if job is None:
                self._json(404, {"error": "Job not found."})
                return
            cancel: threading.Event | None = job.get("cancel")
            if cancel is not None:
                cancel.set()
            with _LOCK:
                _JOBS[job_id]["status"] = "cancelled"
                _JOBS[job_id]["progress"] = "Cancellation requested."
            self._json(200, {"cancelled": job_id})
        elif self.path.startswith("/api/"):
            self._proxy_api("DELETE")
        else:
            self.send_error(404)

    def _generate(self, job_id: str, prompt: str, cancel: threading.Event,
                  sketch_data: bytes | None = None, sketch_name: str | None = None) -> None:
        """Run the full generation pipeline via HybridOrchestrator."""

        def progress(message: str) -> None:
            with _LOCK:
                if job_id in _JOBS:
                    _JOBS[job_id]["progress"] = message

        def _release_lock() -> None:
            global _ACTIVE_JOB
            with _LOCK:
                if _ACTIVE_JOB == job_id:
                    _ACTIVE_JOB = None

        try:
            if cancel.is_set():
                with _LOCK:
                    _JOBS[job_id].update(status="cancelled", progress="Cancelled before start.")
                return

            from sketchforge.orchestration.hybrid_orchestrator import get_hybrid_orchestrator
            orch = get_hybrid_orchestrator()

            # Retrieve the HybridJob already created in do_POST.
            hjob = orch.get_job(job_id)
            if hjob is None:
                raise RuntimeError(f"Orchestrator job {job_id} not found.")

            # If inline sketch bytes arrived, analyze them now.
            if sketch_data and hjob.design_doc is None:
                try:
                    from sketchforge.vision import analyze, load_image_bytes
                    from sketchforge.vision.to_design_ir import (
                        build_nemotron_layout_block, vision_result_to_document
                    )
                    loaded = load_image_bytes(sketch_data, sketch_name or "sketch.png")
                    res = analyze(loaded)
                    hjob.design_doc = vision_result_to_document(res, sketch_name=sketch_name or "Sketch")
                    hjob.layout_block = build_nemotron_layout_block(res, sketch_name=sketch_name or "Sketch")
                except Exception as exc:  # noqa: BLE001
                    log.warning("Could not analyze inline sketch: %s", exc)

            target_dir = repo_root() / "output" / "projects"
            target_dir.mkdir(parents=True, exist_ok=True)

            # Mirror HybridJob state transitions into the _JOBS polling dict.
            _orig_transition = hjob.transition

            def _patched_transition(new_state, progress_msg):
                _orig_transition(new_state, progress_msg)
                with _LOCK:
                    if job_id in _JOBS:
                        _JOBS[job_id]["progress"] = progress_msg
                        _JOBS[job_id]["state"] = new_state.value

            hjob.transition = _patched_transition  # type: ignore[method-assign]

            def _on_preview_ready(job) -> None:
                if job.project_root and job.project_root.is_dir():
                    slug = job.project_root.name
                    preview_url = _start_project_preview(slug, job.project_root)
                    job.preview_url = preview_url
                    with _LOCK:
                        _PROJECTS[slug] = job.project_root
                        _PREVIEWS[slug] = preview_url

            orch.run_pipeline(job_id, target_dir, on_preview_ready=_on_preview_ready)

            if cancel.is_set():
                with _LOCK:
                    _JOBS[job_id].update(status="cancelled", progress="Cancelled after generation.")
                return

            # Sync final outcome into _JOBS.
            hjob = orch.get_job(job_id)
            if hjob is None or hjob.status == "failed":
                error_msg = (hjob.error if hjob else None) or "Generation failed; see server logs."
                with _LOCK:
                    _JOBS[job_id].update(status="failed", error=error_msg)
                return

            if hjob.project_root and hjob.project_slug:
                slug = hjob.project_slug
                preview_url = hjob.preview_url or _PREVIEWS.get(slug, "")

                generation_type = "unknown"
                try:
                    import json as _json
                    meta_file = hjob.project_root / ".sketchforge_meta.json"
                    if meta_file.exists():
                        meta = _json.loads(meta_file.read_text(encoding="utf-8"))
                        generation_type = meta.get("generation", "unknown")
                except Exception:  # noqa: BLE001
                    pass

                discrepancy_data = None
                if hjob.discrepancy is not None:
                    try:
                        discrepancy_data = hjob.discrepancy.to_dict()
                    except Exception:  # noqa: BLE001
                        pass

                with _LOCK:
                    _JOBS[job_id].update(
                        status="complete",
                        project={
                            "name": hjob.project_root.name,
                            "slug": slug,
                            "preview_url": preview_url,
                            "generation_type": generation_type,
                        },
                        discrepancy=discrepancy_data,
                        state=hjob.state.value,
                    )
            else:
                with _LOCK:
                    _JOBS[job_id].update(
                        status="failed",
                        error="No project output produced. Check logs.",
                    )

        except Exception as exc:  # noqa: BLE001
            log.exception("Web studio generation failed")
            with _LOCK:
                _JOBS[job_id].update(status="failed", error=str(exc))
        finally:
            _release_lock()

    def _revise(self, job_id: str, slug: str, instruction: str, cancel: threading.Event) -> None:
        with _LOCK:
            root = _PROJECTS.get(slug)

        def _release_lock() -> None:
            global _ACTIVE_JOB
            with _LOCK:
                if _ACTIVE_JOB == job_id:
                    _ACTIVE_JOB = None

        if root is None:
            with _LOCK:
                _JOBS[job_id].update(status="failed", error="Generated project is no longer available.")
            _release_lock()
            return

        def progress(message: str) -> None:
            with _LOCK:
                _JOBS[job_id]["progress"] = message

        try:
            if cancel.is_set():
                with _LOCK:
                    _JOBS[job_id].update(status="cancelled", progress="Cancelled before start.")
                return
            from sketchforge.generation.ai_generator import ai_revise_project
            updated = ai_revise_project(root, instruction, progress=progress)
            if cancel.is_set():
                with _LOCK:
                    _JOBS[job_id].update(status="cancelled", progress="Cancelled after revision.")
                return
            if not updated:
                raise RuntimeError("AI revision did not produce updated files. Check model configuration.")
            with _LOCK:
                _JOBS[job_id].update(status="complete", project={"name": root.name, "slug": slug})
        except Exception as exc:  # noqa: BLE001
            log.exception("Web studio revision failed")
            with _LOCK:
                _JOBS[job_id].update(status="failed", error=str(exc))
        finally:
            _release_lock()

    def _serve_preview(self, path: str) -> None:
        parts = path.split("/", 3)
        if len(parts) < 3:
            self.send_error(404)
            return
        slug = unquote(parts[2])
        relative = unquote(parts[3]) if len(parts) > 3 else "home.html"
        with _LOCK:
            root = _PROJECTS.get(slug)
        if root is None:
            self.send_error(404)
            return
        target = (root / relative).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            self.send_error(404)
            return
        self._static(target)

    def _proxy_api(self, method: str, *, slug: str | None = None, api_path: str | None = None) -> None:
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen

        if not slug:
            ref = urlparse(self.headers.get("Referer", "")).path.split("/")
            slug = unquote(ref[2]) if len(ref) > 2 and ref[1] == "preview" else ""
        with _LOCK:
            root = _PROJECTS.get(slug)
        if root is None:
            self._json(503, {"error": "No active generated project is associated with this request."})
            return
        # Generated projects use a local Flask API on a per-project port. Start it lazily.
        servers = getattr(self.server, "backend_servers", {})
        backend = servers.get(slug)
        if backend is None:
            try:
                from sketchforge.generation.backend_server import BackendServer
                backend = BackendServer()
                port = backend.start(root)
                if port is None:
                    self._json(503, {"error": "The generated backend could not start."})
                    return
                self.server.backend_servers[slug] = backend
            except Exception as exc:  # noqa: BLE001
                self._json(503, {"error": str(exc)})
                return
        suffix = api_path or self.path
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))) if method in {"POST", "PUT", "PATCH"} else None
        request = Request(f"http://127.0.0.1:{backend.port}{suffix}", data=body, method=method,
                          headers={
                              "Content-Type": self.headers.get("Content-Type", "application/json"),
                              "X-Studio-Token": backend.session_token or "",
                          })
        try:
            with urlopen(request, timeout=10) as response:
                payload, status = response.read(), response.status
        except HTTPError as exc:
            payload, status = exc.read(), exc.code
        except URLError as exc:
            self._json(502, {"error": f"Backend unavailable: {exc.reason}"})
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _static(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)


def serve_studio(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the browser studio until interrupted."""
    server = StudioServer((host, port), StudioHandler)
    server.backend_servers = {}
    print(f"SketchForge Studio is available at http://{host}:{server.server_port}/studio", flush=True)
    try:
        server.serve_forever()
    finally:
        for backend in server.backend_servers.values():
            backend.stop()
        for backend in _BACKENDS:
            backend.stop()
        for preview_server in _PREVIEW_SERVERS:
            preview_server.shutdown()
            preview_server.server_close()
        server.server_close()


def _start_project_preview(slug: str, root: Path) -> str:
    """Serve one project on its own loopback origin and proxy its /api calls."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    from sketchforge.generation.backend_server import BackendServer

    backend = BackendServer()
    backend_port = backend.start(root)
    _BACKENDS.append(backend)

    class ProjectHandler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            path = urlparse(self.path).path
            if path == "/__sketchforge/save" and self.command == "POST":
                relative = unquote(pathlib_path_from_referer(self.headers.get("Referer", "")))
                target = (root / relative).resolve()
                if target.parent != root.resolve() or target.name not in {"home.html", "projects.html"}:
                    self.send_error(400)
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length > 2 * 1024 * 1024:
                        raise ValueError("document too large")
                    data = json.loads(self.rfile.read(length))
                    html = data.get("html", "")
                    if not isinstance(html, str) or "<html" not in html.lower():
                        raise ValueError("invalid document")
                    target.write_text(html, encoding="utf-8")
                except (ValueError, json.JSONDecodeError) as exc:
                    self.send_error(400, str(exc))
                    return
                self.send_response(204)
                self.end_headers()
                return
            if path.startswith("/api/"):
                if backend_port is None:
                    payload = json.dumps({"error": "Generated backend did not start. Install project requirements."}).encode()
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))) if self.command in {"POST", "PUT", "PATCH"} else None
                req = Request(f"http://127.0.0.1:{backend_port}{self.path}", data=body, method=self.command,
                              headers={
                                  "Content-Type": self.headers.get("Content-Type", "application/json"),
                                  "X-Studio-Token": backend.session_token or "",
                              })
                try:
                    with urlopen(req, timeout=10) as resp:
                        payload, status = resp.read(), resp.status
                except HTTPError as exc:
                    payload, status = exc.read(), exc.code
                except URLError as exc:
                    payload, status = json.dumps({"error": str(exc.reason)}).encode(), 502
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)
                return
            relative = unquote(urlparse(self.path).path).lstrip("/") or "home.html"
            target = (root / relative).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                self.send_error(404)
                return
            payload = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix.lower() == ".html":
                monitor = (b"<script data-sketchforge-editor>(function(){function report(m,l){parent.postMessage({type:'sketchforge-error',message:String(m),line:l||'?'},'*')}"
                           b"addEventListener('error',e=>report(e.message,e.lineno));addEventListener('unhandledrejection',e=>report(e.reason));"
                           b"['dragenter','dragover'].forEach(t=>addEventListener(t,e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy'}}));addEventListener('drop',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();[...e.dataTransfer.files].filter(f=>f.type.startsWith('image/')||f.type.startsWith('video/')).forEach(file=>parent.postMessage({type:'sf-file-drop',file},'*'))}});"
                           b"let f=window.fetch.bind(window);window.fetch=(...a)=>f(...a).then(r=>{if(!r.ok)report('HTTP '+r.status+' '+a[0],'API');return r});"
                           b"function save(){let d=document.documentElement.cloneNode(true);d.querySelectorAll('[data-sketchforge-editor]').forEach(x=>x.remove());fetch('/__sketchforge/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({html:'<!doctype html>'+d.outerHTML})}).then(r=>{if(!r.ok)throw Error();parent.postMessage({type:'sf-edit-saved'},'*')}).catch(()=>parent.postMessage({type:'sf-edit-error'},'*'))}"
                           b"let active=null;document.addEventListener('click',e=>{if(!window.sfEditMode)return;if(e.target.closest('[data-sketchforge-editor]'))return;e.preventDefault();e.stopPropagation();if(active)active.style.outline='';active=e.target;active.style.outline='2px solid #7c65e8';parent.postMessage({type:'sf-element-selected',text:active.innerText||active.alt||active.tagName},'*')},true);"
                           b"document.addEventListener('dblclick',e=>{if(!window.sfEditMode||!active)return;e.preventDefault();active.contentEditable='true';active.focus()});document.addEventListener('focusout',e=>{if(e.target.contentEditable==='true'){e.target.contentEditable='false';e.target.style.outline='';active=null;save()}},true);"
                           b"addEventListener('message',e=>{if(e.source!==parent)return;if(e.data?.type==='sf-snapshot'){parent.postMessage({type:'sf-state',state:{url:location.href,scrollX,scrollY,fields:[...document.querySelectorAll('input,textarea,select')].map((x,i)=>({i,value:x.value,checked:x.checked}))}},'*')}"
                           b"if(e.data?.type==='sf-edit-mode'){window.sfEditMode=!!e.data.enabled;document.body.style.cursor=window.sfEditMode?'crosshair':'';parent.postMessage({type:'sf-edit-mode-ready'},'*')}"
                           b"if(e.data?.type==='sf-theme'){let s=document.getElementById('sf-theme-style');if(!s){s=document.createElement('style');s.id='sf-theme-style';document.head.appendChild(s)}s.textContent=e.data.theme==='dark'?'html,body{background:#17171b!important;color:#f2f0f7!important;color-scheme:dark}body header,body nav,body aside,body main,body section,body article,body form{background-color:#222127!important;color:#f2f0f7!important}body input,body textarea,body select,body button{background-color:#302e36!important;color:#f2f0f7!important;border-color:#55515f!important}':'html,body{background:#fff!important;color:#202027!important;color-scheme:light}body header,body nav,body aside,body main,body section,body article,body form{background-color:#f7f7fa!important;color:#202027!important}body input,body textarea,body select,body button{background-color:#fff!important;color:#202027!important;border-color:#c9c8d0!important}'}"
                           b"if(e.data?.type==='sf-insert-media'||e.data?.type==='sf-insert-image'){let el;if(e.data.kind==='video'){el=document.createElement('video');el.controls=true;el.playsInline=true}else{el=document.createElement('img');el.alt='Uploaded image'}el.src=e.data.url;el.style.cssText='max-width:min(100%,640px);height:auto;display:block;margin:16px;border-radius:8px';if(active&&active.parentElement)active.insertAdjacentElement('afterend',el);else(document.querySelector('main')||document.body).appendChild(el);active=el;save()}"
                           b"if(e.data?.type==='sf-add-text'){let el=document.createElement('h2');el.textContent='Add your text';el.contentEditable='true';el.style.cssText='padding:12px;border:1px dashed #7c65e8;min-height:44px';(document.querySelector('main')||document.body).appendChild(el);el.focus();active=el;el.addEventListener('blur',()=>{el.contentEditable='false';el.style.border='';save()},{once:true})}"
                           b"if(e.data?.type==='sf-restore'){let s=e.data.state||{};(s.fields||[]).forEach(x=>{let el=document.querySelectorAll('input,textarea,select')[x.i];if(el){el.value=x.value;el.checked=x.checked}});scrollTo(s.scrollX||0,s.scrollY||0)}})})()</script>")
                payload = payload.replace(b"</head>", monitor + b"</head>", 1)
            self.send_response(200)
            self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"} else ""))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = _handle
        do_POST = _handle
        do_PUT = _handle
        do_DELETE = _handle
        do_OPTIONS = _handle

        def log_message(self, fmt: str, *args) -> None:
            log.info("[preview %s] %s", slug, fmt % args)

    preview_server = ThreadingHTTPServer(("127.0.0.1", 0), ProjectHandler)
    preview_server.daemon_threads = True
    threading.Thread(target=preview_server.serve_forever, daemon=True, name=f"sketchforge-preview-{slug}").start()
    _PREVIEW_SERVERS.append(preview_server)
    return f"http://127.0.0.1:{preview_server.server_port}/home.html"


def pathlib_path_from_referer(referer: str) -> str:
    """Return the generated HTML page name for the editor save request."""
    from urllib.parse import urlparse
    name = Path(urlparse(referer).path).name
    return name if name in {"home.html", "projects.html"} else ""
