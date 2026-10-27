"""Text-related checks: overflow, clipping, size and contrast.

Width uses the shared estimate in :mod:`sketchforge.domain.typography` (not a font engine), so a
"TEXT_OVERFLOW" means *probably does not fit*, within roughly +-10% of real glyph advances.
"""

from __future__ import annotations

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.schema import ComponentType, DesignDocument
from sketchforge.domain.color_system import contrast_ratio, effective_background, text_color_rgb
from sketchforge.domain.typography import estimate_text_width, line_box_height
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.evaluation.issues import Issue
from sketchforge.rendering.svg_renderer import BUTTON_PAD, INPUT_PAD


def horizontal_padding(ctype: ComponentType) -> float:
    return {ComponentType.INPUT: INPUT_PAD, ComponentType.BUTTON: BUTTON_PAD}.get(ctype, 0.0)


def text_fits_width(text: str, font_size: float, weight: int, box_w: float, pad: float) -> float:
    """Excess of the estimated width over the available width (<= 0 means it fits)."""
    return estimate_text_width(text, font_size, weight) - (box_w - 2 * pad)


def check_text(doc: DesignDocument, c: LayoutConstraints) -> list[Issue]:
    found: list[Issue] = []
    for comp in doc.components:
        if not comp.visible or not comp.text or comp.typography is None:
            continue
        typo, box = comp.typography, comp.bbox
        pad = horizontal_padding(comp.type)
        excess = text_fits_width(comp.text, typo.font_size, typo.font_weight, box.w, pad)
        if excess > c.text_overflow_tolerance_px:
            found.append(Issue(
                I.TEXT_OVERFLOW, (comp.id,),
                f"text of {comp.id} is about {excess:.0f}px wider than its box",
                excess, "",
                {"estimated_width": round(estimate_text_width(comp.text, typo.font_size, typo.font_weight), 3),
                 "available": round(box.w - 2 * pad, 3), "font_size": typo.font_size},
            ))
        need = line_box_height(typo.font_size, typo.line_height)
        if need - box.h > c.text_overflow_tolerance_px:
            found.append(Issue(
                I.TEXT_CLIPPED, (comp.id,),
                f"{comp.id} is {box.h:.0f}px tall but its text needs {need:.0f}px",
                need - box.h, "", {"needed": round(need, 3), "height": round(box.h, 3)},
            ))
        if typo.font_size < c.min_font_size_px:
            found.append(Issue(
                I.FONT_TOO_SMALL, (comp.id,),
                f"{comp.id} font size {typo.font_size:g}px is below {c.min_font_size_px:g}px",
                c.min_font_size_px - typo.font_size, "", {"font_size": typo.font_size},
            ))
        bg = effective_background(doc, comp)
        fg = text_color_rgb(comp, bg)
        if fg is not None:
            ratio = contrast_ratio(fg, bg)
            if ratio < c.min_contrast_ratio:
                found.append(Issue(
                    I.LOW_CONTRAST, (comp.id,),
                    f"{comp.id} text contrast is {ratio:.2f}:1 (needs {c.min_contrast_ratio:g}:1)",
                    c.min_contrast_ratio - ratio, "",
                    {"ratio": round(ratio, 3), "required": c.min_contrast_ratio},
                ))
    return found
