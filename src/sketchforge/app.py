"""GUI bootstrap. Qt is imported lazily so the CLI works without PySide6."""

from __future__ import annotations

from pathlib import Path


def run_gui(image: Path | None = None, *, screenshot: Path | None = None) -> int:
    """Open the workbench. With ``screenshot`` set, import ``image``, save a PNG of the window and exit."""
    import os
    import sys

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("error: the GUI needs PySide6 (pip install 'sketchforge[ui]'); the CLI demo does not.",
              file=sys.stderr)
        return 2
    if screenshot is not None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from sketchforge.application.app_controller import AppController
    from sketchforge.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("SketchForge")
    app.setStyle("Fusion")
    controller = AppController()
    window = MainWindow(controller)
    window.show()

    if screenshot is not None:
        target = image or (controller.sample_sketches() or [None])[0]
        if target is not None:
            controller.import_sketch(target)
            controller.inject_error("overflow")
            window.canvas.fit()
        for _ in range(5):
            app.processEvents()
        ok = window.grab().save(str(screenshot))
        window.confirm_discard = lambda: True  # type: ignore[method-assign]
        window.close()
        return 0 if ok else 1

    if image is not None:
        window.import_path(image)
    return app.exec()
