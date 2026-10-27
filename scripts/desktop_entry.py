"""PyInstaller entry point for launching the SketchForge desktop workbench."""

from sketchforge.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main(["gui"]))
