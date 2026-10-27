"""Infer component containment and reading order from geometric detections.

This module owns hierarchy inference; the ``vision`` module remains a compatibility import for
the image-analysis pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sketchforge.vision.component_detection import CONTAINER_TYPES, Detection, area_fraction_inside


@dataclass
class LayoutInference:
    parent: dict[int, int | None]
    order: list[int]
    notes: list[str] = field(default_factory=list)

    def children_of(self, uid: int | None) -> list[int]:
        return [child for child in self.order if self.parent[child] == uid]


def _center_in(inner: tuple, outer: tuple) -> bool:
    cx, cy = inner[0] + inner[2] / 2, inner[1] + inner[3] / 2
    return outer[0] <= cx <= outer[0] + outer[2] and outer[1] <= cy <= outer[1] + outer[3]


def infer_hierarchy(detections: list[Detection]) -> LayoutInference:
    """Choose the smallest containing container and order siblings top-to-bottom, left-to-right."""
    containers = [d for d in detections if d.type in CONTAINER_TYPES]
    parent: dict[int, int | None] = {}
    notes: list[str] = []
    for detection in detections:
        best: Detection | None = None
        for container in containers:
            if container.uid == detection.uid or container.area <= detection.area:
                continue
            thin = min(detection.bbox[2], detection.bbox[3]) <= 8
            inside = (
                _center_in(detection.bbox, container.bbox)
                if thin
                else area_fraction_inside(detection.bbox, container.bbox) >= 0.8
            )
            if inside and (best is None or container.area < best.area):
                best = container
        parent[detection.uid] = best.uid if best else None
        if detection.type in {"card", "container"} and best is None:
            notes.append(f"{detection.type} #{detection.uid} is not inside any other container")

    def reading_key(uid: int) -> tuple[int, float]:
        detection = detections[uid]
        return round(detection.bbox[1] / 10), detection.bbox[0]

    order: list[int] = []

    def walk(parent_uid: int | None) -> None:
        for uid in sorted((u for u, p in parent.items() if p == parent_uid), key=reading_key):
            order.append(uid)
            walk(uid)

    walk(None)
    return LayoutInference(parent, order, notes)
