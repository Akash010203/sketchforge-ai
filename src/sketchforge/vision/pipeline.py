"""Vision pipeline: image -> ink mask -> proposals -> classified detections -> hierarchy.

``analyze`` is the single in-process entry point the application controller and the workflow
orchestrator call. Each stage is also importable on its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from sketchforge.bootstrap import VisionConfig
from sketchforge.utilities.timing import Stopwatch
from sketchforge.vision.component_detection import Detection, detect_components
from sketchforge.vision.handwriting_ocr import recognize_regions
from sketchforge.vision.image_loader import LoadedImage
from sketchforge.vision.layout_inference import LayoutInference, infer_hierarchy
from sketchforge.vision.normalization import NormalizedImage, normalize
from sketchforge.vision.perspective import (
    PerspectiveResult,
    correct_perspective,
    map_point_to_source,
)
from sketchforge.vision.preprocessing import PreprocessResult, preprocess
from sketchforge.vision.region_proposals import RegionProposals, build_proposals

_LOCAL_DETECTOR = None
_DETECTOR_LABELS = {
    "header", "footer", "sidebar", "card", "container", "button", "input",
    "text", "heading", "image", "divider", "checkbox", "radio", "unknown",
}


def _model_detections(ink: object) -> tuple[list[Detection] | None, str | None]:
    """Return model detections when enabled and available; None requests CV fallback."""
    global _LOCAL_DETECTOR
    mode = os.environ.get("SKETCHFORGE_COMPONENT_MODEL", "auto").strip().lower()
    if mode in {"0", "false", "off", "disabled"}:
        return None, None
    if mode not in {"", "1", "true", "on", "auto"}:
        return None, f"unknown SKETCHFORGE_COMPONENT_MODEL value {mode!r}; using CV"
    try:
        from sketchforge.models.component_detector.inference import LocalInferenceSession

        if _LOCAL_DETECTOR is None:
            _LOCAL_DETECTOR = LocalInferenceSession()
        import numpy as np

        # LocalInferenceSession expects a conventional grayscale image (dark ink on light paper).
        image = 255 - np.asarray(ink, dtype=np.uint8)
        result = _LOCAL_DETECTOR.predict(image)
        if not result.ok:
            return None, f"component model unavailable ({result.error}); using CV"
        height, width = image.shape[:2]
        side = max(width, height)
        converted: list[Detection] = []
        for item in result.detections:
            label = item.label if item.label in _DETECTOR_LABELS else "unknown"
            x = (item.cx - item.w / 2) * side
            y = (item.cy - item.h / 2) * side
            w, h = item.w * side, item.h * side
            # The model input is top-left padded to square; discard boxes outside the source image.
            x1, y1 = max(0.0, x), max(0.0, y)
            x2, y2 = min(float(width), x + w), min(float(height), y + h)
            if x2 <= x1 or y2 <= y1:
                continue
            converted.append(Detection(
                uid=len(converted), type=label, bbox=(x1, y1, x2 - x1, y2 - y1),
                confidence=max(0.001, min(1.0, float(item.confidence))),
                type_scores={label: 1.0}, evidence=["local component detector"], ambiguous=False,
            ))
        if not converted:
            return None, (
                f"local component model returned no detections "
                f"({result.model_name}, {result.device}); using CV"
            )
        return converted, f"local component model enabled ({result.model_name}, {result.device})"
    except Exception as exc:  # optional runtime must not prevent CV analysis
        return None, f"component model failed ({type(exc).__name__}: {exc}); using CV"


@dataclass
class VisionResult:
    loaded: LoadedImage
    normalized: NormalizedImage
    preprocessed: PreprocessResult
    proposals: RegionProposals
    detections: list[Detection]
    inference: LayoutInference
    design_scale: float  # design pixels per working pixel
    perspective: PerspectiveResult
    timings_ms: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def to_source_scale(self) -> float:
        """Multiply working-pixel coordinates by this to get original-image pixels."""
        return 1.0 / self.normalized.scale

    def source_box(self, working_box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x, y, w, h = working_box
        points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        k = self.to_source_scale
        points = [(px * k, py * k) for px, py in points]
        if self.perspective.corrected and self.perspective.matrix is not None:
            points = [map_point_to_source(p, self.perspective.matrix) for p in points]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def choose_design_scale(frame_bbox: tuple[float, float, float, float], cfg: VisionConfig) -> float:
    _, _, fw, fh = frame_bbox
    target = cfg.design_width_landscape if fw >= fh else cfg.design_width_portrait
    return target / fw


def analyze(
    loaded: LoadedImage,
    cfg: VisionConfig | None = None,
    *,
    force_variant: str | None = None,
    close_kernel: int | None = None,
) -> VisionResult:
    cfg = cfg or VisionConfig()
    clock = Stopwatch()
    with clock.measure("perspective"):
        perspective = correct_perspective(loaded.bgr)
    with clock.measure("normalize"):
        norm = normalize(perspective.bgr, cfg.working_long_side)
    with clock.measure("preprocess"):
        pre = preprocess(norm, force_variant=force_variant, close_kernel=close_kernel)
    with clock.measure("proposals"):
        proposals = build_proposals(pre.ink, pre.stroke_width, cfg.min_component_side_px)
    if os.environ.get("SKETCHFORGE_OCR_MODEL", "").strip():
        with clock.measure("handwriting_ocr"):
            recognized = recognize_regions(norm.gray, proposals.texts)
        for region, text in zip(proposals.texts, recognized, strict=True):
            region.recognized_text = text or None
    scale = choose_design_scale(proposals.frame.bbox, cfg)
    model_note = None
    with clock.measure("classify"):
        detections, model_note = _model_detections(pre.ink)
        if detections is None:
            detections = detect_components(proposals, scale)
    with clock.measure("hierarchy"):
        inference = infer_hierarchy(detections)
    notes = [*perspective.notes, *pre.notes, *proposals.notes, *inference.notes]
    if model_note:
        notes.append(model_note)
    if os.environ.get("SKETCHFORGE_OCR_MODEL", "").strip():
        notes.append(f"handwriting OCR enabled with {os.environ['SKETCHFORGE_OCR_MODEL']}")
    return VisionResult(
        loaded, norm, pre, proposals, detections, inference, scale, perspective, clock.as_dict(), notes
    )
