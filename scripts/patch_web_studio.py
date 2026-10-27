"""Patch web_studio.py _generate to use HybridOrchestrator (text-mode, \n line endings)."""
from pathlib import Path

src = Path("src/sketchforge/ui/web_studio.py")
# Read in text mode: Python converts CRLF -> \n on Windows
content = src.read_text(encoding="utf-8")

# Verify we can find the method signature
if "def _generate(self, job_id: str, prompt: str, cancel: threading.Event) -> None:" not in content:
    print("ERROR: Signature not found. Check file.")
    import sys; sys.exit(1)

OLD = """\
    def _generate(self, job_id: str, prompt: str, cancel: threading.Event) -> None:
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
            root = generate_studio_project(
                prompt, repo_root() / "output" / "projects", progress=progress
            )
            if cancel.is_set():
                with _LOCK:
                    _JOBS[job_id].update(status="cancelled", progress="Cancelled after generation.")
                return
            slug = root.name
            progress("Starting preview server and SQLite API\u2026")
            preview_url = _start_project_preview(slug, root)

            # Verification & discrepancy repair loop
            discrepancy_data = None
            try:
                from sketchforge.verification.discrepancy_repair import run_discrepancy_repair_loop
                report = run_discrepancy_repair_loop(
                    project_root=root,
                    preview_url=preview_url,
                    design_doc=None,
                    max_attempts=1,
                    progress=progress,
                )
                discrepancy_data = report.to_dict()
            except Exception as d_exc:  # noqa: BLE001
                log.warning("Discrepancy verification skipped: %s", d_exc)

            with _LOCK:
                _PROJECTS[slug] = root
                _PREVIEWS[slug] = preview_url
                _JOBS[job_id].update(
                    status="complete",
                    project={"name": root.name, "slug": slug, "preview_url": preview_url},
                    discrepancy=discrepancy_data,
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("Web studio generation failed")
            with _LOCK:
                _JOBS[job_id].update(status="failed", error=str(exc))
        finally:
            _release_lock()
"""

NEW = """\
    def _generate(self, job_id: str, prompt: str, cancel: threading.Event,
                  sketch_data: bytes | None = None, sketch_name: str | None = None) -> None:
        \"\"\"Run the full generation pipeline via HybridOrchestrator.\"\"\"

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
"""

if OLD in content:
    new_content = content.replace(OLD, NEW, 1)
    # Write back preserving the original line endings (the file is CRLF)
    # Python's text mode open will convert \n -> \r\n on write on Windows
    src.write_text(new_content, encoding="utf-8")
    print("SUCCESS: _generate patched.")
else:
    # Diagnostic: show diffs in the surrounding area
    idx = content.find("def _generate(self, job_id:")
    print(f"Method found at index: {idx}")
    if idx >= 0:
        snippet = content[idx:idx+200]
        print("Found text:")
        print(repr(snippet))
    print("\nExpected OLD start:")
    print(repr(OLD[:200]))
