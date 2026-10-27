"""Default visual theme: turns a component *type* into style and typography.

The sketch tells us where things are and roughly what they are, not what colour they should be.
The theme supplies sensible, readable defaults; every value stays editable in the Design IR.
"""

from __future__ import annotations

from dataclasses import dataclass

from sketchforge.design_ir.schema import ComponentType, Style, Typography


@dataclass(frozen=True)
class Theme:
    name: str = "slate-blue"
    page_background: str = "#ffffff"
    text: str = "#0f172a"
    muted: str = "#64748b"
    placeholder: str = "#64748b"
    surface: str = "#ffffff"
    surface_alt: str = "#f1f5f9"
    border: str = "#cbd5e1"
    border_soft: str = "#e2e8f0"
    primary: str = "#2563eb"
    on_primary: str = "#ffffff"
    image_fill: str = "#e2e8f0"
    image_mark: str = "#94a3b8"

    def style_for(self, ctype: ComponentType, corner_radius: float | None = None) -> Style:
        t = ComponentType
        radius = corner_radius if corner_radius is not None and corner_radius > 0 else None
        if ctype is t.HEADER or ctype is t.FOOTER:
            return Style(fill=self.surface_alt, stroke=self.border_soft, stroke_width=1.0)
        if ctype is t.SIDEBAR:
            return Style(fill=self.surface_alt, stroke=self.border_soft, stroke_width=1.0)
        if ctype is t.CARD:
            return Style(fill=self.surface, stroke=self.border_soft, stroke_width=1.0,
                         corner_radius=radius or 10.0)
        if ctype is t.CONTAINER:
            return Style(fill="transparent", stroke=self.border_soft, stroke_width=1.0,
                         corner_radius=radius or 0.0)
        if ctype is t.BUTTON:
            return Style(fill=self.primary, stroke="none", corner_radius=radius or 6.0)
        if ctype is t.INPUT:
            return Style(fill=self.surface, stroke=self.border, stroke_width=1.0,
                         corner_radius=radius or 4.0)
        if ctype is t.CHECKBOX:
            return Style(fill=self.surface, stroke=self.muted, stroke_width=1.5, corner_radius=3.0)
        if ctype is t.RADIO:
            return Style(fill=self.surface, stroke=self.muted, stroke_width=1.5, corner_radius=500.0)
        if ctype is t.IMAGE:
            return Style(fill=self.image_fill, stroke="none", corner_radius=radius or 0.0)
        if ctype is t.DIVIDER:
            return Style(fill=self.border, stroke="none")
        return Style()

    def typography_for(self, ctype: ComponentType, font_size: float) -> Typography | None:
        t = ComponentType
        if ctype is t.HEADING:
            return Typography(font_size=font_size, font_weight=700, color=self.text)
        if ctype is t.TEXT:
            return Typography(font_size=font_size, color=self.text)
        if ctype is t.BUTTON:
            return Typography(font_size=font_size, font_weight=600, text_align="center",
                              color=self.on_primary)
        if ctype is t.INPUT:
            return Typography(font_size=font_size, color=self.placeholder)
        return None


DEFAULT_THEME = Theme()
