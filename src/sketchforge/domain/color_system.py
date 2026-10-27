"""Colour maths: WCAG contrast and effective backgrounds."""

from __future__ import annotations

from sketchforge.design_ir.document import ancestors_of
from sketchforge.design_ir.schema import Component, DesignDocument

RGB = tuple[float, float, float]


def hex_to_rgba(color: str) -> tuple[int, int, int, float] | None:
    """(r, g, b, alpha 0..1) or None for transparent/none."""
    if color in ("transparent", "none"):
        return None
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    alpha = int(color[7:9], 16) / 255.0 if len(color) == 9 else 1.0
    return r, g, b, alpha


def rgb_to_hex(rgb: RGB) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _linear(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: RGB) -> float:
    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG 2.x contrast ratio, 1..21."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _blend(over: tuple[int, int, int, float], under: RGB) -> RGB:
    r, g, b, a = over
    return (r * a + under[0] * (1 - a), g * a + under[1] * (1 - a), b * a + under[2] * (1 - a))


def effective_background(doc: DesignDocument, comp: Component, *, include_self: bool = True) -> RGB:
    """The colour actually behind a component's text: the first opaque fill walking up from the
    component (translucent fills are blended over what lies beneath them)."""
    chain = ([comp] if include_self else []) + ancestors_of(doc, comp.id)
    layers: list[tuple[int, int, int, float]] = []
    for node in chain:
        fill = hex_to_rgba(node.style.fill if node.id != doc.root_id else doc.page.background)
        if fill is None:
            continue
        layers.append(fill)
        if fill[3] >= 0.999:
            break
    base: RGB = (255.0, 255.0, 255.0)
    for layer in reversed(layers):
        base = _blend(layer, base)
    return base


def text_color_rgb(comp: Component, background: RGB) -> RGB | None:
    if comp.typography is None:
        return None
    rgba = hex_to_rgba(comp.typography.color)
    if rgba is None:
        return None
    return _blend(rgba, background)


def best_text_color(background: RGB, preferred: str | None = None, minimum: float = 4.5) -> str:
    """Smallest change to ``preferred`` that reaches ``minimum`` contrast, else black/white."""
    black, white = (15.0, 23.0, 42.0), (255.0, 255.0, 255.0)  # slate-900, white
    if preferred:
        rgba = hex_to_rgba(preferred)
        if rgba is not None:
            base = (float(rgba[0]), float(rgba[1]), float(rgba[2]))
            if contrast_ratio(base, background) >= minimum:
                return preferred
            target = black if relative_luminance(background) > 0.18 else white
            for step in range(1, 21):  # walk the colour toward the target until it passes
                t = step / 20.0
                mixed = tuple(round(base[i] * (1 - t) + target[i] * t) for i in range(3))
                # test the colour that will actually be stored (8-bit channels), not the float mix
                if contrast_ratio(mixed, background) >= minimum:
                    # past the halfway point the colour has changed character anyway: use the
                    # clean target instead of an arbitrary in-between grey
                    return rgb_to_hex(target if t >= 0.5 else mixed)
    return rgb_to_hex(black if contrast_ratio(black, background) >= contrast_ratio(white, background) else white)
