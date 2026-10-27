"""End-to-End Verification of the entire SKETCHFORGE Sketch-to-App Pipeline.

Tests:
1. Hand-drawn sketch rendering & OpenCV layout analysis
2. Nemotron layout block & Design IR extraction
3. HybridOrchestrator pipeline execution (Stage 1 plan -> Stage 2 files)
4. Full-stack application generation (frontend HTML/CSS/JS + backend Flask API + SQLite schema)
5. Route alignment: frontend JS endpoints match backend API routes (/api/<entities>)
6. Backend runtime execution: BackendServer boots up, passes token gate, handles CRUD
7. CORS origin & security validation
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sketchforge.datasets.synthetic_generator import ALL_LAYOUTS, render_sketch
from sketchforge.generation.backend_server import BackendServer
from sketchforge.orchestration.hybrid_orchestrator import (
    HybridJobState,
    get_hybrid_orchestrator,
)
from sketchforge.vision.image_loader import load_image_bytes
from sketchforge.vision.pipeline import analyze
from sketchforge.vision.to_design_ir import (
    build_nemotron_layout_block,
    vision_result_to_document,
)
import cv2


def run_e2e():
    print("=" * 70)
    print("SKETCHFORGE END-TO-END PIPELINE VERIFICATION")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Step 1: Create a realistic sketch image and analyze with OpenCV
    # ------------------------------------------------------------------
    print("\n[Step 1] Generating sketch & running OpenCV vision analysis...")
    sketch_img, _ = render_sketch(ALL_LAYOUTS["login_page"](), seed=42, condition="clean")
    ok, png_buf = cv2.imencode(".png", sketch_img)
    assert ok, "Failed to encode sketch image"
    sketch_bytes = png_buf.tobytes()

    loaded_image = load_image_bytes(sketch_bytes, "test_sketch.png")
    vision_res = analyze(loaded_image)
    print(f"  ✓ OpenCV analyzed sketch: {loaded_image.width}x{loaded_image.height}")
    print(f"  ✓ Detections found: {len(vision_res.detections)}")
    assert len(vision_res.detections) > 0, "No detections found in sketch"

    # ------------------------------------------------------------------
    # Step 2: Build Nemotron Layout Block & Design IR
    # ------------------------------------------------------------------
    print("\n[Step 2] Building Nemotron Layout Block & Design IR...")
    layout_block = build_nemotron_layout_block(vision_res, sketch_name="test_sketch.png")
    design_doc = vision_result_to_document(vision_res, sketch_name="test_sketch.png")
    print(f"  ✓ Layout block components: {len(layout_block.get('components', []))}")
    assert len(layout_block.get("components", [])) > 0, "No components in layout block"

    # ------------------------------------------------------------------
    # Step 3: Run Orchestrator Pipeline
    # ------------------------------------------------------------------
    print("\n[Step 3] Running Hybrid Orchestrator Pipeline...")
    temp_dir = Path(tempfile.mkdtemp(prefix="sketchforge_e2e_"))
    try:
        orch = get_hybrid_orchestrator()
        prompt = "Create a project task manager to track deliverables and milestones"
        hjob = orch.create_job(
            prompt,
            sketch_data=sketch_bytes,
            sketch_name="test_sketch.png",
        )
        print(f"  ✓ Created HybridJob: {hjob.id}")

        progress_log = []
        preview_ready_called = []

        def on_preview(j):
            preview_ready_called.append(j.id)

        completed_job = orch.run_pipeline(
            hjob.id,
            temp_dir,
            on_preview_ready=on_preview,
        )

        print(f"  ✓ Pipeline finished with state: {completed_job.state.value}")
        print(f"  ✓ Status: {completed_job.status}")
        assert completed_job.status in ("complete", "success"), f"Pipeline failed: {completed_job.error}"
        assert completed_job.project_root is not None, "project_root is None"
        project_root = Path(completed_job.project_root)
        print(f"  ✓ Generated project at: {project_root}")

        # ------------------------------------------------------------------
        # Step 4: Verify Generated Full-Stack Files
        # ------------------------------------------------------------------
        print("\n[Step 4] Verifying generated project structure...")
        expected_files = [
            "index.html",
            "home.html",
            "projects.html",
            "css/style.css",
            "js/home.js",
            "js/projects.js",
            "backend/api.py",
            "backend/logic.py",
            "backend/database.py",
            "backend/models.py",
            "backend/schema.sql",
            "requirements.txt",
        ]
        for rel in expected_files:
            file_path = project_root / rel
            assert file_path.is_file(), f"Missing required file: {rel}"
            size = file_path.stat().st_size
            assert size > 0, f"File {rel} is empty!"
            print(f"  ✓ {rel:<22} ({size} bytes)")

        # ------------------------------------------------------------------
        # Step 5: Verify Route Alignment between Frontend & Backend
        # ------------------------------------------------------------------
        print("\n[Step 5] Checking Frontend-Backend route alignment...")
        home_js = (project_root / "js" / "home.js").read_text(encoding="utf-8")
        api_py = (project_root / "backend" / "api.py").read_text(encoding="utf-8")

        # Find route called by JS
        import re
        fetch_matches = re.findall(r"fetch\(['\"]/api/([a-zA-Z0-9_\-]+)", home_js)
        assert fetch_matches, "No /api/ fetch found in js/home.js"
        js_route = fetch_matches[0]
        print(f"  ✓ Frontend fetches: /api/{js_route}")

        # Verify backend api.py exposes this route
        backend_route_pattern = f"/api/{js_route}"
        assert backend_route_pattern in api_py, f"Backend api.py does not define {backend_route_pattern}!"
        print(f"  ✓ Backend exposes route: {backend_route_pattern}")
        assert "/api/submissions" not in home_js or js_route == "submissions", "Hardcoded /api/submissions in JS!"

        # ------------------------------------------------------------------
        # Step 6: Boot BackendServer & Test Live API
        # ------------------------------------------------------------------
        print("\n[Step 6] Booting sandboxed BackendServer & Testing Live API...")
        backend = BackendServer()
        preview_origin = "http://127.0.0.1:8000"
        port = backend.start(project_root, cors_origin=preview_origin)
        assert port is not None, "BackendServer failed to start!"
        print(f"  ✓ BackendServer running on port: {port}")
        time.sleep(1.0)  # wait for Flask to initialize

        try:
            # 6a. Health endpoint
            health_req = Request(f"http://127.0.0.1:{port}/api/health")
            with urlopen(health_req, timeout=5) as resp:
                assert resp.status == 200
                health_data = json.loads(resp.read().decode())
                assert health_data.get("ok") is True or health_data.get("status") in ("ok", "healthy")
                print(f"  ✓ /api/health -> 200 OK: {health_data}")

            # 6b. Token gate check: request WITHOUT X-Studio-Token must fail (401)
            unauth_req = Request(f"http://127.0.0.1:{port}/api/{js_route}")
            try:
                urlopen(unauth_req, timeout=5)
                assert False, "Request without token should have failed with 401"
            except HTTPError as err:
                assert err.code == 401, f"Expected 401, got {err.code}"
                print("  ✓ Security Gate: Request without X-Studio-Token rejected (401 Unauthorized)")

            # 6c. Token gate check: request WITH X-Studio-Token must succeed (200)
            token_headers = {
                "X-Studio-Token": backend.session_token,
                "Content-Type": "application/json",
                "Origin": preview_origin,
            }
            list_req = Request(f"http://127.0.0.1:{port}/api/{js_route}", headers=token_headers)
            with urlopen(list_req, timeout=5) as resp:
                assert resp.status == 200
                items = json.loads(resp.read().decode())
                assert isinstance(items, list)
                print(f"  ✓ GET /api/{js_route} -> 200 OK (initial items: {len(items)})")
                cors_header = resp.headers.get("Access-Control-Allow-Origin")
                print(f"  ✓ CORS header returned: {cors_header}")
                assert cors_header in (preview_origin, "*"), f"CORS mismatch: {cors_header}"

            # 6d. POST to create a record
            post_payload = json.dumps({"title": "Deliverable 1 - Sketch Pipeline"}).encode("utf-8")
            post_req = Request(
                f"http://127.0.0.1:{port}/api/{js_route}",
                data=post_payload,
                headers=token_headers,
                method="POST",
            )
            with urlopen(post_req, timeout=5) as resp:
                assert resp.status in (200, 201)
                created = json.loads(resp.read().decode())
                item_id = created.get("id")
                assert item_id is not None, f"Created item has no id: {created}"
                print(f"  ✓ POST /api/{js_route} -> Created record ID={item_id}: {created}")

            # 6e. GET again: verify item is present in SQLite database
            with urlopen(list_req, timeout=5) as resp:
                items = json.loads(resp.read().decode())
                assert len(items) == 1, f"Expected 1 item, got {len(items)}"
                assert items[0].get("id") == item_id
                print(f"  ✓ SQLite persistence verified: retrieved item ID={item_id}")

            # 6f. DELETE the record
            del_req = Request(
                f"http://127.0.0.1:{port}/api/{js_route}/{item_id}",
                headers=token_headers,
                method="DELETE",
            )
            with urlopen(del_req, timeout=5) as resp:
                assert resp.status == 200
                del_resp = json.loads(resp.read().decode())
                print(f"  ✓ DELETE /api/{js_route}/{item_id} -> Deleted: {del_resp}")

            # 6g. GET once more: verify deletion
            with urlopen(list_req, timeout=5) as resp:
                items = json.loads(resp.read().decode())
                assert len(items) == 0, f"Expected 0 items after deletion, got {len(items)}"
                print("  ✓ Item deleted successfully from database")

        finally:
            backend.stop()
            print("  ✓ BackendServer stopped cleanly")

        print("\n" + "=" * 70)
        print(">>> ALL END-TO-END PIPELINE CHECKS PASSED PERFECTLY! <<<")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_e2e()
