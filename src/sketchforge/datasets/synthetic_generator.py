"""Programmatic hand-drawn-style sketch generator with exact ground truth.

This is the seed of the Phase 5 synthetic-data pipeline. It draws wobbly pen strokes (rectangles
with overshooting or slightly open corners, rounded buttons, X-marked image boxes, scribbled
"text"), then degrades the page like a phone photo (paper tint, uneven light, shadow, blur, noise,
JPEG). Every element carries a ground-truth label, so detection can be *measured*.

IMPORTANT LIMITATION: these are synthetic sketches. They stand in for real human drawings until a
real-sketch evaluation set exists (see docs/KNOWN_LIMITATIONS.md). Results on them must never be
reported as results on real sketches.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

Box = tuple[float, float, float, float]  # x, y, w, h in canvas pixels


# --------------------------------------------------------------------------- spec data classes
@dataclass(frozen=True)
class SketchElement:
    kind: str  # frame|rect|rounded|xbox|circle|checkbox|text|heading|hline|vline
    box: Box
    gt_type: str | None = None  # None: drawn, but not a separate ground-truth component
    parent: int | None = None  # index of the ground-truth parent element


@dataclass(frozen=True)
class SketchSpec:
    name: str
    canvas: tuple[int, int]  # width, height
    elements: tuple[SketchElement, ...]


@dataclass(frozen=True)
class Condition:
    """Photo conditions. ``pen`` and ``paper`` are gray levels (0 black .. 255 white)."""

    name: str
    paper: int = 245
    pen: int = 40
    thickness: int = 3
    blur: float = 0.6
    noise: float = 2.0
    shadow: float = 0.0  # 0 = none, else darkness of a soft diagonal shadow (0..0.6)
    gradient: float = 0.04  # left-to-right illumination falloff
    jpeg_quality: int = 92


CONDITIONS: dict[str, Condition] = {
    c.name: c
    for c in (
        Condition("clean"),
        Condition("shadow", paper=240, noise=4.0, shadow=0.35, gradient=0.10, jpeg_quality=85),
        Condition("noisy", noise=9.0, blur=0.9, jpeg_quality=55),
        Condition("lowcontrast", paper=205, pen=115, noise=4.0),
        Condition("blur", blur=1.8),
        Condition("thin", thickness=2, blur=0.8),
        Condition("thick", thickness=5, blur=0.8),
    )
}


# --------------------------------------------------------------------------- layouts
class _Builder:
    def __init__(self) -> None:
        self.items: list[SketchElement] = []

    def add(self, kind: str, box: Box, gt: str | None = None, parent: int | None = None) -> int:
        self.items.append(SketchElement(kind, box, gt, parent))
        return len(self.items) - 1


def login_page() -> SketchSpec:
    b = _Builder()
    frame = b.add("frame", (60, 50, 1120, 800), "page")
    header = b.add("rect", (60, 50, 1120, 80), "header", frame)
    b.add("xbox", (90, 62, 56, 56), "image", header)
    for x, w in ((780, 90), (900, 90), (1020, 100)):
        b.add("text", (x, 82, w, 18), "text", header)
    card = b.add("rect", (410, 210, 420, 440), "card", frame)
    b.add("heading", (450, 240, 220, 32), "heading", card)
    for y, tw in ((310, 120), (390, 100)):
        field = b.add("rect", (450, y, 340, 48), "input", card)
        b.add("text", (462, y + 16, tw, 16), None, field)
    b.add("checkbox", (450, 470, 24, 24), "checkbox", card)
    b.add("text", (486, 474, 150, 16), "text", card)
    button = b.add("rounded", (450, 530, 340, 52), "button", card)
    b.add("text", (560, 548, 120, 16), None, button)
    b.add("text", (520, 604, 200, 14), "text", card)
    b.add("hline", (100, 740, 1040, 0), "divider", frame)
    b.add("text", (500, 775, 240, 14), "text", frame)
    return SketchSpec("login_page", (1240, 900), tuple(b.items))


def dashboard() -> SketchSpec:
    b = _Builder()
    frame = b.add("frame", (60, 50, 1120, 800), "page")
    header = b.add("rect", (60, 50, 1120, 80), "header", frame)
    b.add("xbox", (82, 66, 48, 48), "image", header)
    b.add("text", (160, 82, 160, 20), "text", header)
    sidebar = b.add("rect", (60, 130, 220, 720), "sidebar", frame)
    for y, w in ((160, 120), (210, 110), (260, 130), (310, 100)):
        b.add("text", (90, y, w, 16), "text", sidebar)
    for i in range(3):
        card = b.add("rect", (320 + i * 280, 160, 250, 180), "card", frame)
        b.add("heading", (340 + i * 280, 182, 150, 26), "heading", card)
        b.add("text", (340 + i * 280, 250, 190, 16), "text", card)
    b.add("xbox", (320, 380, 810, 250), "image", frame)
    b.add("hline", (320, 660, 810, 0), "divider", frame)
    button = b.add("rounded", (320, 690, 170, 52), "button", frame)
    b.add("text", (360, 708, 90, 16), None, button)
    return SketchSpec("dashboard", (1240, 900), tuple(b.items))


def mobile_form() -> SketchSpec:
    b = _Builder()
    frame = b.add("frame", (40, 40, 620, 1020), "page")
    header = b.add("rect", (40, 40, 620, 70), "header", frame)
    b.add("xbox", (60, 52, 44, 44), "image", header)
    b.add("text", (290, 66, 120, 20), "text", header)
    b.add("heading", (80, 150, 300, 34), "heading", frame)
    b.add("xbox", (80, 210, 540, 200), "image", frame)
    for y, tw in ((450, 150), (530, 120), (610, 170)):
        field = b.add("rect", (80, y, 540, 52), "input", frame)
        b.add("text", (96, y + 18, tw, 16), None, field)
    for y, tw in ((700, 120), (750, 140)):
        b.add("circle", (80, y, 26, 26), "radio", frame)
        b.add("text", (122, y + 4, tw, 16), "text", frame)
    button = b.add("rounded", (80, 840, 540, 58), "button", frame)
    b.add("text", (310, 860, 80, 16), None, button)
    b.add("text", (240, 950, 220, 14), "text", frame)
    return SketchSpec("mobile_form", (700, 1100), tuple(b.items))


def landing_page() -> SketchSpec:
    """Held-out layout: NOT used while tuning the detector."""
    b = _Builder()
    frame = b.add("frame", (50, 40, 1140, 820), "page")
    header = b.add("rect", (50, 40, 1140, 64), "header", frame)
    b.add("text", (80, 62, 110, 18), "text", header)
    for x in (820, 930, 1040):
        b.add("text", (x, 62, 80, 18), "text", header)
    b.add("heading", (140, 170, 520, 44), "heading", frame)
    b.add("text", (140, 240, 460, 16), "text", frame)
    b.add("text", (140, 272, 400, 16), "text", frame)
    b.add("rounded", (140, 330, 190, 56), "button", frame)
    b.add("xbox", (700, 150, 420, 300), "image", frame)
    b.add("hline", (80, 520, 1080, 0), "divider", frame)
    for i in range(3):
        card = b.add("rect", (110 + i * 360, 570, 320, 200), "card", frame)
        b.add("xbox", (130 + i * 360, 586, 70, 70), "image", card)
        b.add("text", (130 + i * 360, 690, 240, 16), "text", card)
        b.add("text", (130 + i * 360, 722, 180, 16), "text", card)
    return SketchSpec("landing_page", (1240, 900), tuple(b.items))


def settings_page() -> SketchSpec:
    """Held-out layout: NOT used while tuning the detector."""
    b = _Builder()
    frame = b.add("frame", (80, 60, 1000, 780), "page")
    header = b.add("rect", (80, 60, 1000, 70), "header", frame)
    b.add("heading", (110, 78, 200, 30), "heading", header)
    panel = b.add("rect", (140, 180, 880, 520), "card", frame)
    for i, y in enumerate((220, 300, 380, 460)):
        b.add("text", (170, y + 12, 160 + 20 * i, 16), "text", panel)
        field = b.add("rect", (520, y, 460, 46), "input", panel)
        b.add("text", (534, y + 15, 130, 16), None, field)
    b.add("checkbox", (170, 560, 24, 24), "checkbox", panel)
    b.add("text", (210, 564, 200, 16), "text", panel)
    b.add("checkbox", (170, 610, 24, 24), "checkbox", panel)
    b.add("text", (210, 614, 220, 16), "text", panel)
    b.add("rounded", (820, 760, 200, 54), "button", frame)
    return SketchSpec("settings_page", (1160, 900), tuple(b.items))


TUNING_LAYOUTS = {"login_page": login_page, "dashboard": dashboard, "mobile_form": mobile_form}
HELDOUT_LAYOUTS = {"landing_page": landing_page, "settings_page": settings_page}
ALL_LAYOUTS = {**TUNING_LAYOUTS, **HELDOUT_LAYOUTS}


# --------------------------------------------------------------------------- stroke primitives
_SHIFT = 4
_SCALE = 1 << _SHIFT


def _densify(points: list[tuple[float, float]] | np.ndarray, step: float = 10.0) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:], strict=True):
        dist = float(np.hypot(*(b - a)))
        n = max(1, int(dist / step))
        for i in range(1, n + 1):
            out.append(a + (b - a) * (i / n))
    return np.asarray(out)


def _noisy_path(path: np.ndarray, rng: np.random.Generator, amp: float) -> np.ndarray:
    """Add smooth perpendicular wobble that is anchored (zero) at both ends."""
    n = len(path)
    if n < 3 or amp <= 0:
        return path
    tangent = np.gradient(path, axis=0)
    norm = np.hypot(tangent[:, 0], tangent[:, 1])[:, None]
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1) / np.maximum(norm, 1e-9)
    walk = np.cumsum(rng.normal(0.0, amp * 0.55, n))
    walk -= np.linspace(walk[0], walk[-1], n)
    walk = np.clip(walk, -amp * 1.6, amp * 1.6)
    return path + walk[:, None] * normal


def _stroke(canvas: np.ndarray, path: np.ndarray, thickness: int) -> None:
    pts = np.round(path * _SCALE).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(canvas, [pts], False, 255, thickness, cv2.LINE_AA, _SHIFT)


def _line(canvas, a, b, rng, th, amp=1.0) -> None:
    _stroke(canvas, _noisy_path(_densify([a, b]), rng, amp), th)


def _rect_sides(canvas, box: Box, rng, th: int, *, gap: float = 2.2, over: float = 5.0) -> None:
    x, y, w, h = box
    corners = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=float)
    corners += rng.normal(0, 0.9, corners.shape)
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        d = (b - a) / max(float(np.hypot(*(b - a))), 1e-9)
        ext_a = -rng.uniform(0, gap) if rng.random() < 0.3 else rng.uniform(0, over)
        ext_b = -rng.uniform(0, gap) if rng.random() < 0.3 else rng.uniform(0, over)
        _line(canvas, a - d * ext_a, b + d * ext_b, rng, th, 1.0)


def _rounded_rect(canvas, box: Box, rng, th: int, radius: float | None = None) -> None:
    x, y, w, h = box
    r = radius if radius is not None else min(14.0, h / 3.0)
    pts: list[tuple[float, float]] = []
    corners = (
        (x + r, y + r, math.pi, 1.5 * math.pi),
        (x + w - r, y + r, 1.5 * math.pi, 2 * math.pi),
        (x + w - r, y + h - r, 0.0, 0.5 * math.pi),
        (x + r, y + h - r, 0.5 * math.pi, math.pi),
    )
    for cx, cy, a0, a1 in corners:
        for t in np.linspace(a0, a1, 7):
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    pts.append(pts[0])
    pts.extend(pts[1:3])  # slight overlap where the pen returns
    _stroke(canvas, _noisy_path(_densify(pts, 8.0), rng, 0.9), th)


def _ellipse(canvas, box: Box, rng, th: int) -> None:
    x, y, w, h = box
    cx, cy, rx, ry = x + w / 2, y + h / 2, w / 2, h / 2
    start = rng.uniform(0, 2 * math.pi)
    t = np.linspace(start, start + 2 * math.pi + 0.35, 48)
    path = np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1)
    _stroke(canvas, _noisy_path(path, rng, 0.8), th)


def _xbox(canvas, box: Box, rng, th: int) -> None:
    x, y, w, h = box
    _rect_sides(canvas, box, rng, th, gap=1.5)
    _line(canvas, (x + 2, y + 2), (x + w - 2, y + h - 2), rng, th, 1.2)
    _line(canvas, (x + w - 2, y + 2), (x + 2, y + h - 2), rng, th, 1.2)


def _scribble(canvas, box: Box, rng, th: int, heading: bool = False) -> None:
    """Pen scribble that reads as handwriting: separate letter-like strokes grouped in words."""
    x, y, w, h = box
    th = max(1, th - 1) if not heading else th
    base_y = y + h * 0.82
    xh = h * (0.5 if not heading else 0.55)
    asc = h * 0.95
    cx = x
    word_left = int(rng.integers(3, 8))
    while cx < x + w - 3:
        gw = float(rng.uniform(0.32, 0.55)) * h
        if cx + gw > x + w:
            break
        k = int(rng.integers(3, 6))
        xs = np.linspace(cx, cx + gw, k)
        tops = np.where(rng.random(k) < 0.22, asc, xh * rng.uniform(0.7, 1.0, k))
        ys = np.where(np.arange(k) % 2 == 0, base_y, base_y - tops)
        if rng.random() < 0.18:  # an "o"-like loop
            t = np.linspace(0, 2 * math.pi, 14)
            loop = np.stack(
                [cx + gw / 2 + gw / 2 * np.cos(t), base_y - xh / 2 + xh / 2 * np.sin(t)], axis=1
            )
            _stroke(canvas, loop, th)
        else:
            _stroke(canvas, np.stack([xs, ys], axis=1), th)
        cx += gw + float(rng.uniform(1.5, 3.0))
        word_left -= 1
        if word_left <= 0:
            cx += h * 0.7
            word_left = int(rng.integers(3, 8))


# --------------------------------------------------------------------------- rendering
def _draw_layer(spec: SketchSpec, rng: np.random.Generator, cond: Condition) -> np.ndarray:
    w, h = spec.canvas
    layer = np.zeros((h, w), dtype=np.uint8)
    th = cond.thickness
    for el in spec.elements:
        x, y, bw, bh = el.box
        if el.kind in ("frame", "rect", "checkbox"):
            _rect_sides(layer, el.box, rng, th)
        elif el.kind == "rounded":
            _rounded_rect(layer, el.box, rng, th)
        elif el.kind == "xbox":
            _xbox(layer, el.box, rng, th)
        elif el.kind == "circle":
            _ellipse(layer, el.box, rng, th)
        elif el.kind == "text":
            _scribble(layer, el.box, rng, th)
        elif el.kind == "heading":
            _scribble(layer, el.box, rng, th + 1, heading=True)
        elif el.kind == "hline":
            _line(layer, (x, y), (x + bw, y), rng, th, 1.0)
        elif el.kind == "vline":
            _line(layer, (x, y), (x, y + bh), rng, th, 1.0)
        else:
            raise ValueError(f"unknown sketch element kind: {el.kind}")
    return layer


def _illumination(shape: tuple[int, int], cond: Condition, rng: np.random.Generator) -> np.ndarray:
    h, w = shape
    xx, yy = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    light = 1.0 - cond.gradient * xx
    if cond.shadow > 0:
        angle = rng.uniform(0.3, 1.2)
        proj = xx * math.cos(angle) + yy * math.sin(angle)
        edge = rng.uniform(0.35, 0.6)
        light = light * (1.0 - cond.shadow / (1.0 + np.exp(-(proj - edge) * 9.0)))
    return light.astype(np.float32)


def render_sketch(
    spec: SketchSpec, seed: int = 0, condition: str | Condition = "clean"
) -> tuple[np.ndarray, dict]:
    """Return ``(BGR image, ground truth)``. Deterministic for a given (spec, seed, condition)."""
    cond = CONDITIONS[condition] if isinstance(condition, str) else condition
    rng = np.random.default_rng(seed)
    w, h = spec.canvas
    alpha = _draw_layer(spec, rng, cond).astype(np.float32) / 255.0

    paper = np.full((h, w, 3), cond.paper, dtype=np.float32)
    paper *= np.array([0.97, 0.985, 1.0], dtype=np.float32)  # warm paper tint (BGR)
    paper += rng.normal(0, 1.2, (h, w, 1)).astype(np.float32)
    ink = np.full((h, w, 3), cond.pen, dtype=np.float32)
    img = paper * (1 - alpha[..., None]) + ink * alpha[..., None]
    img *= _illumination((h, w), cond, rng)[..., None]
    if cond.blur > 0:
        img = cv2.GaussianBlur(img, (0, 0), cond.blur)
    if cond.noise > 0:
        img += rng.normal(0, cond.noise, img.shape).astype(np.float32)
    img = np.clip(img, 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, cond.jpeg_quality])
    if ok:
        img = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return img, ground_truth(spec, seed, cond)


def ground_truth(spec: SketchSpec, seed: int, cond: Condition) -> dict:
    comps = []
    index_map: dict[int, int] = {}
    for i, el in enumerate(spec.elements):
        if el.gt_type is None:
            continue
        x, y, bw, bh = el.box
        if el.kind in ("hline", "vline"):
            pad = 2.0
            box = [x - (pad if el.kind == "vline" else 0), y - (pad if el.kind == "hline" else 0)]
            box += [bw + (2 * pad if el.kind == "vline" else 0), bh + (2 * pad if el.kind == "hline" else 0)]
        else:
            box = [x, y, bw, bh]
        index_map[i] = len(comps)
        comps.append(
            {
                "index": len(comps),
                "type": el.gt_type,
                "bbox": [float(v) for v in box],
                "parent": None,
                "_src_parent": el.parent,
            }
        )
    for comp in comps:
        parent = comp.pop("_src_parent")
        comp["parent"] = index_map.get(parent) if parent is not None else None
    return {
        "layout": spec.name,
        "canvas": list(spec.canvas),
        "seed": seed,
        "condition": cond.name,
        "components": comps,
    }
