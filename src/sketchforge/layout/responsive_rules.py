"""Responsive layout repair rules for generated CSS.

The Design IR keeps one authoritative desktop geometry. These rules derive a small-screen
fallback from explicit container layout metadata without mutating that geometry: multi-column
grids and horizontal flex rows collapse into a vertical, full-width stack.
"""

from __future__ import annotations

from sketchforge.design_ir.schema import DesignDocument

DEFAULT_BREAKPOINT_PX = 768


def responsive_css(doc: DesignDocument, breakpoint_px: int = DEFAULT_BREAKPOINT_PX) -> str:
    """Return CSS media-query repairs for explicit layouts that need a narrow-screen fallback."""
    if breakpoint_px < 1:
        raise ValueError("breakpoint_px must be positive")
    rules: list[str] = []
    for container in doc.components:
        layout = container.layout
        if layout is None or layout.mode not in {"grid", "flex"}:
            continue
        children = doc.children_of(container.id)
        if len(children) < 2:
            continue
        should_stack = ((layout.mode == "grid" and (layout.columns or 1) > 1)
                        or (layout.mode == "flex" and layout.direction == "row"))
        if not should_stack:
            continue
        child_selectors = ", ".join(f"#sf-{child.id}" for child in children)
        rules.extend([
            f"  #sf-{container.id} {{ display:flex; flex-direction:column; gap:{layout.gap:g}px; }}",
            f"  {child_selectors} {{ position:relative; left:auto; top:auto; width:100%; max-width:100%; }}",
        ])
    if not rules:
        return ""
    return f"@media (max-width: {breakpoint_px}px) {{\n" + "\n".join(rules) + "\n}\n"


__all__ = ["DEFAULT_BREAKPOINT_PX", "responsive_css"]
