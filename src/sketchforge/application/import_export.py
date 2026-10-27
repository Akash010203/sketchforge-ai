"""Export a design (and optionally its report) as plain files other tools can open."""

from __future__ import annotations

from pathlib import Path

from sketchforge.design_ir.schema import DesignDocument
from sketchforge.design_ir.serialization import save_document
from sketchforge.evaluation.report import RepairReport
from sketchforge.rendering.renderer import render_all
from sketchforge.utilities.paths import ensure_dir


def export_design(
    doc: DesignDocument, directory: str | Path, stem: str = "design", report: RepairReport | None = None
) -> dict[str, Path]:
    """Write ``<stem>.svg/.html/.css/.png/.json`` (+ report files) and return their paths."""
    out = ensure_dir(directory)
    paths = render_all(doc).save(out, stem)
    paths["json"] = save_document(doc, out / f"{stem}.json")
    if report is not None:
        paths.update({f"report_{k}": v for k, v in report.save(out, f"{stem}_report").items()})
    return paths
