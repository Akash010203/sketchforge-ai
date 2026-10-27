"""Bridge: VisionResult → DesignDocument + AppSpec.

This is the missing translation layer between the OpenCV detection pipeline
and the Nemotron generation pipeline.

``vision_result_to_document`` converts a :class:`~sketchforge.vision.pipeline.VisionResult`
(containing typed ``Detection`` objects with absolute bounding boxes and a
containment hierarchy) into a :class:`~sketchforge.design_ir.schema.DesignDocument`.

``vision_result_to_spec`` then calls ``spec_from_document`` to derive a full
:class:`~sketchforge.generation.app_specification.AppSpec` from that document.

Both objects are serialisable and can be embedded verbatim in the Nemotron
Stage-1 prompt so the model follows the detected layout precisely instead of
inventing an arbitrary one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sketchforge.vision.pipeline import VisionResult

# ---------------------------------------------------------------------------
# Component-type mapping: vision detection type -> DesignDocument ComponentType
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "header": "HEADER",
    "footer": "FOOTER",
    "sidebar": "SIDEBAR",
    "card": "CARD",
    "container": "CONTAINER",
    "button": "BUTTON",
    "input": "INPUT",
    "text": "TEXT",
    "heading": "HEADING",
    "image": "IMAGE",
    "divider": "DIVIDER",
    "checkbox": "CHECKBOX",
    "radio": "RADIO",
    "unknown": "CONTAINER",
}


def vision_result_to_document(result: "VisionResult", sketch_name: str = "Sketch") -> "object":
    """Convert a VisionResult into a DesignDocument.

    Absolute bounding boxes are scaled from working-pixel space into design
    pixels (using ``result.design_scale``) so all measurements have the same
    meaning as the rest of the Design IR.

    The containment hierarchy from ``result.inference`` is preserved: every
    child component is added after its parent so the document's index stays
    consistent.

    Returns a :class:`~sketchforge.design_ir.schema.DesignDocument`.
    """
    from sketchforge.design_ir.document import add_component, make_component_id, new_document
    from sketchforge.design_ir.schema import BBox, Component, ComponentType, DetectionInfo, Style

    # Derive canvas dimensions in design pixels.
    frame_x, frame_y, frame_w, frame_h = result.proposals.frame.bbox
    scale = result.design_scale
    canvas_w = round(frame_w * scale)
    canvas_h = round(frame_h * scale)

    doc = new_document(
        name=sketch_name,
        width=float(canvas_w),
        height=float(canvas_h),
        device="desktop" if canvas_w >= canvas_h else "mobile",
    )

    detections = result.detections
    inference = result.inference
    uid_to_id: dict[int, str] = {}  # vision uid -> document component id

    def _component_type(vision_type: str) -> ComponentType:
        name = _TYPE_MAP.get(vision_type, "CONTAINER")
        try:
            return ComponentType[name]
        except KeyError:
            return ComponentType.CONTAINER

    def _bbox(detection) -> BBox:
        x, y, w, h = detection.bbox
        # Translate so the frame origin is (0, 0) in the document.
        return BBox(
            x=round((x - frame_x) * scale, 2),
            y=round((y - frame_y) * scale, 2),
            w=round(w * scale, 2),
            h=round(h * scale, 2),
        )

    # Walk in pre-order (parents before children) so parent IDs exist when
    # children are inserted.
    for uid in inference.order:
        detection = detections[uid]
        parent_uid = inference.parent.get(uid)
        parent_id = uid_to_id.get(parent_uid) if parent_uid is not None else doc.root_id

        ctype = _component_type(detection.type)
        cid = make_component_id(doc, detection.type)
        uid_to_id[uid] = cid

        comp = Component(
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
        )
        add_component(doc, comp)

    return doc


def vision_result_to_spec(
    result: "VisionResult",
    sketch_name: str = "Sketch",
    app_name: str | None = None,
) -> tuple["object", "object"]:
    """Convert a VisionResult into (DesignDocument, AppSpec).

    Returns both objects so callers can embed whichever level of detail
    is appropriate in their prompts. Both are dataclasses and can be
    serialised with ``dataclasses.asdict``.
    """
    from sketchforge.generation.app_specification import spec_from_document

    doc = vision_result_to_document(result, sketch_name=sketch_name)
    spec = spec_from_document(doc, app_name=app_name or sketch_name)
    return doc, spec


def build_nemotron_layout_block(result: "VisionResult", sketch_name: str = "Sketch") -> dict:
    """Return the structured JSON block that is embedded in the Nemotron Stage-1 prompt.

    The block contains three complementary representations of the detected layout:

    ``app_spec``
        A serialised :class:`~sketchforge.generation.app_specification.AppSpec`
        with pages, forms, actions, and entity suggestions.

    ``components``
        A flat list of every detected component with its type, confidence,
        bounding box in **design pixels**, recognised label text, and its
        parent component ID. This gives Nemotron the exact spatial grid it
        needs to reproduce the sketch layout faithfully.

    ``hierarchy``
        A readable tree summary (e.g. ``header > button, input``) for the
        system prompt so the model can reason about nesting without parsing
        the full component list.

    ``canvas``
        Width and height of the design canvas in design pixels.
    """
    import dataclasses

    doc, spec = vision_result_to_spec(result, sketch_name=sketch_name)

    # Build flat component list with parent references.
    components = []
    from sketchforge.design_ir.document import preorder

    for comp in preorder(doc):
        if comp.id == doc.root_id:
            continue  # skip the synthetic page root
        components.append({
            "id": comp.id,
            "type": comp.type.value if hasattr(comp.type, "value") else str(comp.type),
            "parent_id": comp.parent_id,
            "bbox_design_px": {
                "x": comp.bbox.x,
                "y": comp.bbox.y,
                "w": comp.bbox.w,
                "h": comp.bbox.h,
            },
            "label": comp.text or "",
            "confidence": comp.detection.confidence if comp.detection else 1.0,
        })

    # Build a human-readable hierarchy string for the system message.
    def _hierarchy_lines(parent_id: str, depth: int = 0) -> list[str]:
        lines = []
        children = [c for c in doc.components if c.parent_id == parent_id and c.id != doc.root_id]
        for child in children:
            ctype = child.type.value if hasattr(child.type, "value") else str(child.type)
            label = f' "{child.text}"' if child.text else ""
            lines.append("  " * depth + f"* {ctype}{label}")
            lines.extend(_hierarchy_lines(child.id, depth + 1))
        return lines

    hierarchy_text = "\n".join(_hierarchy_lines(doc.root_id)) or "(no components detected)"

    return {
        "canvas": {
            "width_design_px": doc.page.width,
            "height_design_px": doc.page.height,
            "device": doc.page.viewport.device,
        },
        "app_spec": dataclasses.asdict(spec),
        "components": components,
        "hierarchy": hierarchy_text,
    }


def build_nemotron_layout_block_from_document(doc: "object", app_name: str | None = None) -> dict:
    """Build the Nemotron layout block directly from an existing DesignDocument."""
    import dataclasses
    from sketchforge.design_ir.document import preorder
    from sketchforge.generation.app_specification import spec_from_document

    spec = spec_from_document(doc, app_name=app_name or getattr(doc, "name", "Sketch App"))

    components = []
    for comp in preorder(doc):
        if comp.id == doc.root_id:
            continue
        components.append({
            "id": comp.id,
            "type": comp.type.value if hasattr(comp.type, "value") else str(comp.type),
            "parent_id": comp.parent_id,
            "bbox_design_px": {
                "x": comp.bbox.x,
                "y": comp.bbox.y,
                "w": comp.bbox.w,
                "h": comp.bbox.h,
            },
            "label": comp.text or "",
            "confidence": comp.detection.confidence if comp.detection else 1.0,
        })

    def _hierarchy_lines(parent_id: str, depth: int = 0) -> list[str]:
        lines = []
        children = [c for c in doc.components if c.parent_id == parent_id and c.id != doc.root_id]
        for child in children:
            ctype = child.type.value if hasattr(child.type, "value") else str(child.type)
            label = f' "{child.text}"' if child.text else ""
            lines.append("  " * depth + f"* {ctype}{label}")
            lines.extend(_hierarchy_lines(child.id, depth + 1))
        return lines

    hierarchy_text = "\n".join(_hierarchy_lines(doc.root_id)) or "(no components detected)"

    return {
        "canvas": {
            "width_design_px": doc.page.width,
            "height_design_px": doc.page.height,
            "device": doc.page.viewport.device,
        },
        "app_spec": dataclasses.asdict(spec),
        "components": components,
        "hierarchy": hierarchy_text,
    }

