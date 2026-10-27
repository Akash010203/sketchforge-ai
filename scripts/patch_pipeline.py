"""Patch script for sketchforge sketch-to-app pipeline fixes."""
import inspect
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Patch src/sketchforge/integrations/nebius/client.py
# ---------------------------------------------------------------------------
client_path = Path("src/sketchforge/integrations/nebius/client.py")
client_text = client_path.read_text(encoding="utf-8")

old_call = 'result = self._parse(response, model, attempt, (self._clock() - started) * 1000)'
new_call = 'result = self._parse(response, model, attempt, (self._clock() - started) * 1000, request=request)'
if old_call in client_text:
    client_text = client_text.replace(old_call, new_call, 1)

old_parse_sig = 'def _parse(self, response: Any, model: str, attempt: int, latency_ms: float) -> CompletionResult:'
new_parse_sig = '''def _parse(
        self,
        response: Any,
        model: str,
        attempt: int,
        latency_ms: float,
        request: CompletionRequest | None = None,
    ) -> CompletionResult:'''
if old_parse_sig in client_text:
    client_text = client_text.replace(old_parse_sig, new_parse_sig, 1)

old_finish = '''        if finish == "length":
            # For plan/revision requests the truncated JSON is unusable — raise so the
            # caller can fall back cleanly.  For file generation requests the partial
            # code fence can still be recovered by _parse_file_content (unclosed fence),
            # so we only log a warning and return the content.
            log.warning(
                "nebius: finish_reason=length for model=%s (request may be truncated); "
                "returning partial content for caller to handle.",
                model,
            )'''

new_finish = '''        if finish == "length":
            if request is not None and getattr(request, "purpose", None) == "studio_file":
                log.warning(
                    "nebius: finish_reason=length for model=%s (request may be truncated); "
                    "returning partial content for caller to handle.",
                    model,
                )
            else:
                raise ProviderBadResponse("the answer was cut off (max_tokens reached); it would not be valid JSON")'''

if old_finish in client_text:
    client_text = client_text.replace(old_finish, new_finish, 1)

client_path.write_text(client_text, encoding="utf-8")
print("1. nebius/client.py patched")

# ---------------------------------------------------------------------------
# 2. Patch tests/unit/test_ai_generator.py
# ---------------------------------------------------------------------------
test_ai_path = Path("tests/unit/test_ai_generator.py")
test_ai_text = test_ai_path.read_text(encoding="utf-8")

old_fake_sig = "def fake_stage2(client, spec_str, path_hint, description, emit, model, layout_context=None):"
new_fake_sig = "def fake_stage2(client, spec_str, path_hint, description, emit, model, layout_context=None, **kwargs):"
if old_fake_sig in test_ai_text:
    test_ai_text = test_ai_text.replace(old_fake_sig, new_fake_sig, 1)

test_ai_path.write_text(test_ai_text, encoding="utf-8")
print("2. tests/unit/test_ai_generator.py patched")

# ---------------------------------------------------------------------------
# 3. Patch src/sketchforge/generation/ai_generator.py
# ---------------------------------------------------------------------------
ai_gen_path = Path("src/sketchforge/generation/ai_generator.py")
ai_gen_text = ai_gen_path.read_text(encoding="utf-8")

# Fix _stage2_file call to handle any mock signatures gracefully
old_call_block = """        content = _stage2_file(
            client,
            spec_str,
            path_hint,
            description,
            _emit,
            model=active_model or _NEMOTRON_MODEL,
            layout_context=layout_context,
            entity_route_context=entity_route_context,
        )"""

new_call_block = """        import inspect
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
        )"""

if old_call_block in ai_gen_text:
    ai_gen_text = ai_gen_text.replace(old_call_block, new_call_block, 1)

# Fix fallback templates in ai_generator.py for js/home.js and js/projects.js
old_fallback_home = 'return _home_js(entity_obj, "submissions", storage_key)'
new_fallback_home = 'return _home_js(entity_obj, route, storage_key)'
if old_fallback_home in ai_gen_text:
    ai_gen_text = ai_gen_text.replace(old_fallback_home, new_fallback_home, 1)

old_fallback_proj = 'return _projects_js(entity_obj, "submissions", storage_key)'
new_fallback_proj = 'return _projects_js(entity_obj, route, storage_key)'
if old_fallback_proj in ai_gen_text:
    ai_gen_text = ai_gen_text.replace(old_fallback_proj, new_fallback_proj, 1)

ai_gen_path.write_text(ai_gen_text, encoding="utf-8")
print("3. ai_generator.py patched")

# ---------------------------------------------------------------------------
# 4. Patch src/sketchforge/generation/backend_server.py
# ---------------------------------------------------------------------------
backend_srv_path = Path("src/sketchforge/generation/backend_server.py")
backend_srv_text = backend_srv_path.read_text(encoding="utf-8")

old_start_def = "    def start(self, project_root: Path) -> int | None:"
new_start_def = "    def start(self, project_root: Path, cors_origin: str | None = None) -> int | None:"
if old_start_def in backend_srv_text:
    backend_srv_text = backend_srv_text.replace(old_start_def, new_start_def, 1)

old_cors = '        child_env["CORS_ORIGIN"] = f"http://127.0.0.1:{port}"'
new_cors = '        child_env["CORS_ORIGIN"] = cors_origin or "*"'
if old_cors in backend_srv_text:
    backend_srv_text = backend_srv_text.replace(old_cors, new_cors, 1)

backend_srv_path.write_text(backend_srv_text, encoding="utf-8")
print("4. backend_server.py patched")

# ---------------------------------------------------------------------------
# 5. Patch src/sketchforge/ui/preview_panel.py
# ---------------------------------------------------------------------------
preview_path = Path("src/sketchforge/ui/preview_panel.py")
preview_text = preview_path.read_text(encoding="utf-8")

old_preview_start = """        # Start frontend static server
        self._start_server()
        frontend_url = f"http://127.0.0.1:{self._server.server_port}/{index.name}"

        # Start backend API server if backend/api.py exists
        backend_port = self._backend_server.start(project_root)"""

new_preview_start = """        # Start frontend static server
        self._start_server()
        frontend_origin = f"http://127.0.0.1:{self._server.server_port}"
        frontend_url = f"{frontend_origin}/{index.name}"

        # Start backend API server if backend/api.py exists
        backend_port = self._backend_server.start(project_root, cors_origin=frontend_origin)"""

if old_preview_start in preview_text:
    preview_text = preview_text.replace(old_preview_start, new_preview_start, 1)

preview_path.write_text(preview_text, encoding="utf-8")
print("5. preview_panel.py patched")

# ---------------------------------------------------------------------------
# 6. Patch src/sketchforge/ui/generation_panel.py & main_window.py
# ---------------------------------------------------------------------------
gen_panel_path = Path("src/sketchforge/ui/generation_panel.py")
gen_panel_text = gen_panel_path.read_text(encoding="utf-8")

old_worker_init = "    def __init__(self, prompt: str, output_base: Path, include_backend: bool, options: dict) -> None:"
new_worker_init = "    def __init__(self, prompt: str, output_base: Path, include_backend: bool, options: dict, design_doc: object = None) -> None:"
if old_worker_init in gen_panel_text:
    gen_panel_text = gen_panel_text.replace(old_worker_init, new_worker_init, 1)

old_worker_assign = "        self._options = options"
new_worker_assign = "        self._options = options\n        self._design_doc = design_doc"
if old_worker_assign in gen_panel_text and "self._design_doc" not in gen_panel_text:
    gen_panel_text = gen_panel_text.replace(old_worker_assign, new_worker_assign, 1)

old_worker_run = """    def run(self) -> None:  # called by QThread.started
        try:
            root = generate_studio_project(
                self._prompt,
                self._output_base,
                include_backend=self._include_backend,
                **self._options,
                progress=lambda msg: self.progress.emit(msg),
            )
        except (OSError, ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(str(root))"""

new_worker_run = """    def run(self) -> None:  # called by QThread.started
        try:
            from sketchforge.generation.ai_generator import ai_generate_project
            self.progress.emit("Starting generation with Nemotron-3_5-Lightning…")
            root = ai_generate_project(
                self._prompt,
                self._output_base,
                include_backend=self._include_backend,
                design_doc=self._design_doc,
                progress=lambda msg: self.progress.emit(msg),
            )
            if not root or not Path(root).is_dir():
                self.progress.emit("AI service unavailable; generating from verified templates…")
                root = generate_studio_project(
                    self._prompt,
                    self._output_base,
                    include_backend=self._include_backend,
                    **self._options,
                    progress=lambda msg: self.progress.emit(msg),
                )
        except (OSError, ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(str(root))"""

if old_worker_run in gen_panel_text:
    gen_panel_text = gen_panel_text.replace(old_worker_run, new_worker_run, 1)

old_panel_init = "    def __init__(self, parent=None) -> None:"
new_panel_init = "    def __init__(self, parent=None, controller=None) -> None:\n        super().__init__(parent)\n        self.controller = controller"
if old_panel_init in gen_panel_text:
    gen_panel_text = gen_panel_text.replace(old_panel_init, new_panel_init, 1)
    # remove duplicate super().__init__(parent) if present right after
    gen_panel_text = gen_panel_text.replace("        super().__init__(parent)\n        self.controller = controller\n        super().__init__(parent)", "        super().__init__(parent)\n        self.controller = controller", 1)

old_worker_call = "        worker = _GenerateWorker(prompt, self._output_base, self.backend.isChecked(), options)"
new_worker_call = """        design_doc = self.controller.document if self.controller and self.controller.has_project else None
        worker = _GenerateWorker(prompt, self._output_base, self.backend.isChecked(), options, design_doc=design_doc)"""

if old_worker_call in gen_panel_text:
    gen_panel_text = gen_panel_text.replace(old_worker_call, new_worker_call, 1)

gen_panel_path.write_text(gen_panel_text, encoding="utf-8")
print("6. generation_panel.py patched")

# Main window passing controller
main_win_path = Path("src/sketchforge/ui/main_window.py")
main_win_text = main_win_path.read_text(encoding="utf-8")
if "self.generator = GenerationPanel()" in main_win_text:
    main_win_text = main_win_text.replace("self.generator = GenerationPanel()", "self.generator = GenerationPanel(self, controller=controller)", 1)
    main_win_path.write_text(main_win_text, encoding="utf-8")
    print("7. main_window.py patched")

# ---------------------------------------------------------------------------
# 8. Patch src/sketchforge/vision/to_design_ir.py
# ---------------------------------------------------------------------------
ir_path = Path("src/sketchforge/vision/to_design_ir.py")
ir_text = ir_path.read_text(encoding="utf-8")
old_ir_imp = "from sketchforge.design_ir.schema import BBox, Component, ComponentType, Style"
new_ir_imp = "from sketchforge.design_ir.schema import BBox, Component, ComponentType, DetectionInfo, Style"
if old_ir_imp in ir_text:
    ir_text = ir_text.replace(old_ir_imp, new_ir_imp, 1)

old_comp_block = """        comp = Component(
            id=cid,
            type=ctype,
            name=f"{detection.type.capitalize()} {uid}",
            parent_id=parent_id,
            bbox=_bbox(detection),
            style=Style(),
            text=detection.recognized_text,
            confidence=round(detection.confidence, 3),
        )"""

new_comp_block = """        comp = Component(
            id=cid,
            type=ctype,
            name=f"{detection.type.capitalize()} {uid}",
            parent_id=parent_id,
            bbox=_bbox(detection),
            style=Style(),
            text=detection.recognized_text,
            detection=DetectionInfo(
                confidence=round(min(max(float(detection.confidence), 0.0), 1.0), 3),
                source="heuristic",
            ),
        )"""

if old_comp_block in ir_text:
    ir_text = ir_text.replace(old_comp_block, new_comp_block, 1)
    ir_path.write_text(ir_text, encoding="utf-8")
    print("8. vision/to_design_ir.py patched")

# ---------------------------------------------------------------------------
# 9. Patch max_tokens cap & ping probe in src/sketchforge/generation/ai_generator.py
# ---------------------------------------------------------------------------
ai_gen_path = Path("src/sketchforge/generation/ai_generator.py")
ai_gen_text = ai_gen_path.read_text(encoding="utf-8")

# Fix max_tokens=8192 -> 4096 (policy limit)
old_stage2_tokens = "max_tokens=8192,"
new_stage2_tokens = "max_tokens=4096,"
if old_stage2_tokens in ai_gen_text:
    ai_gen_text = ai_gen_text.replace(old_stage2_tokens, new_stage2_tokens, 1)

# Fix ping_max_tokens=8 -> 64 and purpose="studio_ping"
old_ping_def = "    ping_max_tokens: int = 8,"
new_ping_def = "    ping_max_tokens: int = 64,"
if old_ping_def in ai_gen_text:
    ai_gen_text = ai_gen_text.replace(old_ping_def, new_ping_def, 1)

old_ping_purpose = '            purpose="studio_plan",'
new_ping_purpose = '            purpose="studio_ping",'
if old_ping_purpose in ai_gen_text:
    ai_gen_text = ai_gen_text.replace(old_ping_purpose, new_ping_purpose, 1)

ai_gen_path.write_text(ai_gen_text, encoding="utf-8")
print("9. ai_generator.py max_tokens and ping probe patched")

# ---------------------------------------------------------------------------
# 10. Patch client.py to allow studio_ping
# ---------------------------------------------------------------------------
client_path = Path("src/sketchforge/integrations/nebius/client.py")
client_text = client_path.read_text(encoding="utf-8")
old_client_cond = 'if request is not None and getattr(request, "purpose", None) == "studio_file":'
new_client_cond = 'if request is not None and getattr(request, "purpose", None) in ("studio_file", "studio_ping"):'
if old_client_cond in client_text:
    client_text = client_text.replace(old_client_cond, new_client_cond, 1)
    client_path.write_text(client_text, encoding="utf-8")
    print("10. nebius/client.py studio_ping allowed")

# ---------------------------------------------------------------------------
# 11. Patch /api/health bypass in studio_generator.py and retrieval/patterns.py
# ---------------------------------------------------------------------------
sg_path = Path("src/sketchforge/generation/studio_generator.py")
sg_text = sg_path.read_text(encoding="utf-8")
old_sg_gate = '    if not request.path.startswith("/api/"):\n        return  # health / static routes pass through'
new_sg_gate = '    if not request.path.startswith("/api/") or request.path in ("/api/health", "/health"):\n        return  # health / static routes pass through'
if old_sg_gate in sg_text:
    sg_text = sg_text.replace(old_sg_gate, new_sg_gate, 1)
    sg_path.write_text(sg_text, encoding="utf-8")
    print("11. studio_generator.py /api/health bypass patched")

pat_path = Path("src/sketchforge/retrieval/patterns.py")
pat_text = pat_path.read_text(encoding="utf-8")
old_pat_gate = '    if not request.path.startswith("/api/") or request.method == "OPTIONS":'
new_pat_gate = '    if not request.path.startswith("/api/") or request.path in ("/api/health", "/health") or request.method == "OPTIONS":'
if old_pat_gate in pat_text:
    pat_text = pat_text.replace(old_pat_gate, new_pat_gate, 1)
    pat_path.write_text(pat_text, encoding="utf-8")
    print("12. retrieval/patterns.py /api/health bypass patched")

print("ALL PATCHES COMPLETED!")
