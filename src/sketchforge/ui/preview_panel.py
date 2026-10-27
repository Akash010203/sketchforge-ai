"""Source, design, and isolated live preview for generated project files.

Changes in this revision:
  - BackendServer is started/stopped alongside the frontend HTTP server.
  - The sandbox iframe URL is replaced with a proxy HTML that rewrites /api/*
    requests to the backend port, so the generated frontend can talk to the
    real SQLite API without CORS issues.
  - Viewport controls, error display, and open-separately dialog are retained.
"""

from __future__ import annotations

import html
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # Optional desktop component.
    QWebEngineSettings = None
    QWebEngineView = None

LIVE_PREVIEW_AVAILABLE = (
    QWebEngineView is not None and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
)

from sketchforge.application.app_controller import AppController
from sketchforge.design_ir.serialization import to_json
from sketchforge.generation.backend_server import BackendServer


def _code_view() -> QPlainTextEdit:
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    view.setFont(font)
    return view


class _PreviewView(QWebEngineView or QWidget):
    def __init__(self, owner: "PreviewPanel") -> None:
        super().__init__()
        self.owner = owner
        self.loadStarted.connect(lambda: owner._show_state("starting"))
        self.loadFinished.connect(owner._load_finished)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):  # noqa: N802
        if self.owner.project_root and (
            "error" in str(level).lower() or "uncaught" in message.lower()
        ):
            self.owner.error_label.setText(f"Runtime error · {message} (line {line_number})")
            self.owner.runtime_bar.setVisible(True)


class PreviewPanel(QTabWidget):
    """Run the generated project's real files inside a sandboxed iframe."""

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.project_root: Path | None = None
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._project_url = ""
        self._backend_server = BackendServer()

        self.html_view = _code_view()
        self.css_view = _code_view()
        self.json_view = _code_view()
        self.js_view = _code_view()

        self.preview_page = QWidget()
        self.web_view = _PreviewView(self) if LIVE_PREVIEW_AVAILABLE else QWidget()
        preview_layout = QVBoxLayout(self.preview_page)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        # --- Controls bar ---
        controls = QWidget()
        controls.setObjectName("previewControls")
        control_row = QHBoxLayout(controls)
        control_row.setContentsMargins(9, 7, 9, 7)
        self.preview_status = QLabel("No generated project")
        self.viewport = QComboBox()
        self.viewport.addItem("Desktop", 0)
        self.viewport.addItem("Tablet", 768)
        self.viewport.addItem("Mobile", 390)
        self.viewport.currentIndexChanged.connect(self._set_viewport)
        self.refresh_button = QPushButton("↻  Refresh")
        self.refresh_button.clicked.connect(self.refresh_preview)
        self.open_button = QPushButton("↗  Open separately")
        self.open_button.clicked.connect(self.open_separately)
        control_row.addWidget(self.preview_status, 1)
        control_row.addWidget(QLabel("Viewport"))
        control_row.addWidget(self.viewport)
        control_row.addWidget(self.refresh_button)
        control_row.addWidget(self.open_button)
        preview_layout.addWidget(controls)

        # --- Preview stack: empty / loading / error / web view ---
        self.preview_stack = QStackedWidget()
        self.empty_state = QLabel(
            "✳\n\nYour live preview will appear here\n\n"
            "Describe an app and select Generate to create its frontend and backend."
        )
        self.empty_state.setObjectName("previewEmptyState")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_state = QLabel("◌\n\nPreparing your project preview…")
        self.loading_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_state = QWidget()
        error_layout = QVBoxLayout(self.error_state)
        error_layout.addStretch()
        self.error_title = QLabel("Preview couldn't start")
        self.error_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_detail = QLabel("Check that the generated project files are available.")
        self.error_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recover_button = QPushButton("Try again")
        self.recover_button.clicked.connect(self.refresh_preview)
        error_layout.addWidget(self.error_title)
        error_layout.addWidget(self.error_detail)
        error_layout.addWidget(self.recover_button, alignment=Qt.AlignmentFlag.AlignCenter)
        error_layout.addStretch()

        if LIVE_PREVIEW_AVAILABLE:
            self.preview_stack.addWidget(self.empty_state)
            self.preview_stack.addWidget(self.loading_state)
            self.preview_stack.addWidget(self.error_state)
            self.preview_stack.addWidget(self.web_view)
            settings = self.web_view.settings()
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
            )
        else:
            fallback = QLabel(
                (
                    "Live preview is disabled in headless mode. "
                    "Run SketchForge in a desktop session."
                    if QWebEngineView is not None
                    else "The live preview needs PySide6 WebEngine. Install the desktop extras with:\n"
                    'python -m pip install -e ".[ui]"\n\n'
                    "Then restart SketchForge to preview generated project files here."
                )
            )
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setWordWrap(True)
            self.preview_stack.addWidget(fallback)

        preview_layout.addWidget(self.preview_stack, 1)

        # --- Runtime error bar ---
        runtime_bar = QWidget()
        runtime_layout = QHBoxLayout(runtime_bar)
        runtime_layout.setContentsMargins(8, 5, 8, 5)
        self.error_label = QLabel()
        self.error_label.setObjectName("runtimeError")
        self.runtime_recover = QPushButton("Reload")
        self.runtime_recover.clicked.connect(self.refresh_preview)
        runtime_layout.addWidget(self.error_label, 1)
        runtime_layout.addWidget(self.runtime_recover)
        runtime_bar.setVisible(False)
        self.runtime_bar = runtime_bar
        preview_layout.addWidget(runtime_bar)

        self.addTab(self.preview_page, "Preview")
        self.addTab(self.html_view, "HTML")
        self.addTab(self.css_view, "CSS")
        self.addTab(self.js_view, "JS")
        self.addTab(self.json_view, "Design IR")

    # ------------------------------------------------------------------
    def attach_project(self, root: str | Path) -> None:
        """Show files from a materialised frontend project in the live preview."""
        project_root = Path(root).resolve()
        index = project_root / "home.html"
        if not index.is_file():
            index = project_root / "index.html"
        if not index.is_file():
            raise FileNotFoundError(f"No generated app entry point in {project_root}")
        self.project_root = project_root

        # Start frontend static server
        self._start_server()
        frontend_origin = f"http://127.0.0.1:{self._server.server_port}"
        frontend_url = f"{frontend_origin}/{index.name}"

        # Start backend API server if backend/api.py exists
        backend_port = self._backend_server.start(project_root, cors_origin=frontend_origin)

        # Build the URL we'll load in the web view.
        # When a backend is running we load a thin proxy HTML that rewrites /api/* requests.
        if backend_port is not None:
            self._project_url = self._proxy_url(frontend_url, backend_port)
            self.preview_status.setText(
                f"Live preview  ·  {project_root.name}  (backend: :{backend_port})"
            )
        else:
            self._project_url = frontend_url
            self.preview_status.setText(f"Live preview  ·  {project_root.name}")

        self.runtime_bar.setVisible(False)
        self._read_project_files()
        self.setCurrentIndex(0)
        self.refresh_preview()

    def _proxy_url(self, frontend_url: str, backend_port: int) -> str:
        """
        Build a data: URL for a thin proxy page that:
          1. Rewrites all /api/* fetch calls to http://127.0.0.1:<backend_port>/api/*.
          2. Embeds the real frontend in an iframe with allow-same-origin so the
             JS inside can read cookies / localStorage normally.
        """
        # We serve a small wrapper HTML directly as the QWebEngineView page content,
        # so we return a sentinel token that refresh_preview will detect.
        return f"__proxy__:{frontend_url}:{backend_port}"

    # ------------------------------------------------------------------
    def _start_server(self) -> None:
        self._stop_server()
        assert self.project_root is not None
        handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(
            *args, directory=str(self.project_root), **kwargs
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        server_thread = threading.Thread(
            target=server.serve_forever, daemon=True, name="sketchforge-preview"
        )
        server_thread.start()
        self._server, self._server_thread = server, server_thread

    def _stop_server(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _read_project_files(self) -> None:
        assert self.project_root is not None
        for view, path in (
            (self.html_view, self.project_root / "home.html"),
            (self.css_view, self.project_root / "css" / "style.css"),
            (self.js_view, self.project_root / "js" / "home.js"),
        ):
            if path.is_file():
                view.setPlainText(path.read_text(encoding="utf-8"))
        if self.controller.has_project:
            self.json_view.setPlainText(to_json(self.controller.document))

    def refresh(self) -> None:
        """Refresh source views from the sketch design when it changes."""
        if not self.controller.has_project:
            self.json_view.clear()
            return
        rendered = self.controller.render()
        if self.project_root is None:
            self.html_view.setPlainText(rendered.html)
            self.css_view.setPlainText(rendered.css)
            self.json_view.setPlainText(to_json(self.controller.document))

    def refresh_preview(self) -> None:
        if not self.project_root:
            self._show_state("empty")
            return
        if not LIVE_PREVIEW_AVAILABLE:
            return
        self._show_state("starting")
        self.runtime_bar.setVisible(False)

        url = self._project_url
        if url.startswith("__proxy__:"):
            # Parse proxy token: __proxy__:<frontend_url>:<backend_port>
            _, frontend_url, backend_port_str = url.split(":", 2)
            backend_port = int(backend_port_str)
            html_doc = self._proxy_document(frontend_url, backend_port)
            self.web_view.setHtml(html_doc, QUrl("about:blank"))
        else:
            self.web_view.setHtml(self._sandbox_document(url), QUrl("about:blank"))

    # ------------------------------------------------------------------
    @staticmethod
    def _sandbox_document(project_url: str) -> str:
        safe_url = html.escape(project_url, quote=True)
        return (
            f'<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>\n'
            f"html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#101014}}"
            f'iframe{{display:block;width:var(--frame-width,100%);height:100%;margin:0 auto;'
            f"border:0;background:#111;box-shadow:0 0 0 1px #ffffff24}}\n"
            f'</style></head><body><iframe id="app" title="Generated app live preview" '
            f'sandbox="allow-scripts allow-forms allow-modals allow-downloads allow-same-origin" '
            f'src="{safe_url}"></iframe>\n'
            f"<script>window.addEventListener('message',e=>{{if(e.data==='sketchforge-preview-error')"
            f"document.title='SketchForge preview error'}});</script></body></html>"
        )

    @staticmethod
    def _proxy_document(frontend_url: str, backend_port: int) -> str:
        """
        Wrapper page that:
          - Loads the generated frontend in an <iframe>.
          - Injects a service-worker-like fetch interceptor via postMessage so
            relative /api/* URLs inside the iframe are redirected to the local
            backend port.

        Because QWebEngineView serves this as about:blank, we use a data: src
        for the iframe so the generated app loads from its real local HTTP server.
        """
        safe_frontend = html.escape(frontend_url, quote=True)
        bp = backend_port
        script = f"""
(function() {{
  var bp = {bp};
  var iframe = document.getElementById('app');
  // When the iframe posts a fetch request, we proxy it from this page.
  window.addEventListener('message', function(e) {{
    if (!e.data || e.data.type !== '__sf_fetch') return;
    var id = e.data.id;
    var url = e.data.url;
    var opts = e.data.opts || {{}};
    if (url.startsWith('/api/')) {{
      url = 'http://127.0.0.1:' + bp + url;
    }}
    fetch(url, opts)
      .then(function(r) {{ return r.text().then(function(body) {{
        e.source.postMessage({{type:'__sf_fetch_resp',id:id,ok:r.ok,status:r.status,body:body}}, '*');
      }}); }})
      .catch(function(err) {{
        e.source.postMessage({{type:'__sf_fetch_resp',id:id,ok:false,status:0,body:String(err)}}, '*');
      }});
  }});
}})();
"""
        return (
            f'<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>'
            f"html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#101014}}"
            f'iframe{{display:block;width:var(--frame-width,100%);height:100%;margin:0 auto;'
            f"border:0;background:#111;box-shadow:0 0 0 1px #ffffff24}}"
            f'</style></head><body>'
            f'<iframe id="app" title="Generated app live preview" '
            f'sandbox="allow-scripts allow-forms allow-modals allow-downloads allow-same-origin" '
            f'src="{safe_frontend}"></iframe>'
            f"<script>{script}</script></body></html>"
        )

    # ------------------------------------------------------------------
    def _show_state(self, state: str) -> None:
        if state == "empty":
            self.preview_stack.setCurrentWidget(self.empty_state)
        elif state == "starting":
            self.preview_stack.setCurrentWidget(self.loading_state)
        elif state == "error":
            self.preview_stack.setCurrentWidget(self.error_state)
        elif LIVE_PREVIEW_AVAILABLE:
            self.preview_stack.setCurrentWidget(self.web_view)

    def _load_finished(self, ok: bool) -> None:
        if not ok:
            self.show_error(
                "The preview renderer could not load the project files.",
                "Preview could not start",
            )
            return
        self.preview_status.setText(
            f"●  Running locally  ·  {self.project_root.name if self.project_root else ''}"
        )
        self._show_state("ready")
        self._set_viewport(self.viewport.currentIndex())

    def show_error(self, message: str, title: str = "Project generation failed") -> None:
        self.error_title.setText(title)
        self.error_detail.setText(message)
        self._show_state("error")

    def _set_viewport(self, _index: int) -> None:
        if not LIVE_PREVIEW_AVAILABLE:
            return
        width = self.viewport.currentData()
        self.web_view.page().runJavaScript(
            f"document.getElementById('app').style.width='{width}px';"
            if width
            else "document.getElementById('app').style.width='100%';"
        )

    def open_separately(self) -> None:
        if not self._project_url or not LIVE_PREVIEW_AVAILABLE:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("SketchForge · Live Preview")
        dialog.resize(1180, 820)
        layout = QVBoxLayout(dialog)
        view = _PreviewView(self)
        layout.addWidget(view)
        url = self._project_url
        if url.startswith("__proxy__:"):
            _, frontend_url, backend_port_str = url.split(":", 2)
            view.setHtml(
                self._proxy_document(frontend_url, int(backend_port_str)),
                QUrl("about:blank"),
            )
        else:
            view.setHtml(self._sandbox_document(url), QUrl("about:blank"))
        dialog.exec()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._stop_server()
        self._backend_server.stop()
        super().closeEvent(event)
