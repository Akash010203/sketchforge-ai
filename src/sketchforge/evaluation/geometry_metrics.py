"""Fidelity of the design to what was detected in the sketch.

``fidelity`` compares each component's current box with the box the sketch detection implies
(``detection.source_bbox`` mapped through ``metadata.source_transform``). It measures how far
automatic or manual edits have moved the design from the *detections*; it is not evidence that
the detections themselves are right (see evaluation/component_metrics.py for that, on data with
ground truth).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sketchforge.design_ir.geometry import source_to_design
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.evaluation.component_metrics import box_iou


@dataclass
class Fidelity:
    n: int
    mean_iou: float
    mean_position_error_px: float
    max_position_error_px: float
    per_component: dict[str, tuple[float, float]] = field(default_factory=dict)  # id -> (iou, err)

    def as_dict(self) -> dict[str, float]:
        return {
            "fidelity_components": self.n,
            "fidelity_mean_iou": round(self.mean_iou, 4),
            "position_error_mean_px": round(self.mean_position_error_px, 3),
            "position_error_max_px": round(self.max_position_error_px, 3),
        }


def expected_box(doc: DesignDocument, component_id: str):
    comp = doc.require(component_id)
    t = doc.metadata.source_transform
    if t is None or comp.detection is None or comp.detection.source_bbox is None:
        return None
    return source_to_design(comp.detection.source_bbox, t.scale, t.offset_x, t.offset_y)


def fidelity(doc: DesignDocument) -> Fidelity | None:
    """None when the document has no sketch provenance (e.g. built by hand)."""
    per: dict[str, tuple[float, float]] = {}
    for comp in doc.components:
        if comp.id == doc.root_id or not comp.visible:
            continue
        exp = expected_box(doc, comp.id)
        if exp is None:
            continue
        b = comp.bbox
        iou = box_iou((b.x, b.y, b.w, b.h), (exp.x, exp.y, exp.w, exp.h))
        err = math.hypot(b.cx - exp.cx, b.cy - exp.cy)
        per[comp.id] = (iou, err)
    if not per:
        return None
    ious = [v[0] for v in per.values()]
    errs = [v[1] for v in per.values()]
    return Fidelity(len(per), sum(ious) / len(ious), sum(errs) / len(errs), max(errs), per)
