"""The open project: document, undo history, source image and the latest measurements."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2

from sketchforge.design_ir.schema import DesignDocument
from sketchforge.editor.selection import Selection
from sketchforge.editor.undo_redo import UndoStack
from sketchforge.evaluation.evaluator import EvaluationResult
from sketchforge.evaluation.report import RepairReport
from sketchforge.storage.project_store import ProjectMeta, load_project, save_project
from sketchforge.vision.image_loader import LoadedImage, load_image_bytes
from sketchforge.vision.pipeline import VisionResult


@dataclass
class Project:
    name: str
    document: DesignDocument
    stack: UndoStack
    selection: Selection = field(default_factory=Selection)
    source: LoadedImage | None = None
    source_bytes: bytes | None = None
    vision: VisionResult | None = None  # not persisted: re-import to regenerate
    evaluation: EvaluationResult | None = None
    last_report: RepairReport | None = None
    path: Path | None = None
    saved_revision: int = 0

    @classmethod
    def create(cls, name: str, document: DesignDocument, **kw) -> Project:
        return cls(name=name, document=document, stack=UndoStack(document), **kw)

    @property
    def dirty(self) -> bool:
        return self.stack.revision != self.saved_revision

    def save(self, directory: str | Path) -> Path:
        data = self.source_bytes
        if data is None and self.source is not None:
            ok, buf = cv2.imencode(".png", self.source.bgr)
            data = buf.tobytes() if ok else None
        source_name = None
        if self.source is not None:
            source_name = self.source.name if self.source_bytes else Path(self.source.name).stem + ".png"
        meta = ProjectMeta(self.name, source_name, self.source.sha256 if self.source else None)
        root = save_project(directory, self.document, meta, data)
        self.path, self.saved_revision = root, self.stack.revision
        return root

    @classmethod
    def load(cls, directory: str | Path) -> Project:
        doc, meta, source_bytes = load_project(directory)
        source = load_image_bytes(source_bytes, meta.source_file or "sketch.png") if source_bytes else None
        project = cls.create(meta.name, doc, source=source, source_bytes=source_bytes, path=Path(directory))
        return project
