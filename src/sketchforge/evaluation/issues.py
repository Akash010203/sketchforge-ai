"""The issue vocabulary shared by the evaluator, the diagnosis step and the repair engine."""

from __future__ import annotations

from dataclasses import dataclass, field

# Issue codes. Each has a precise definition in docs/EVALUATION.md.
OVERFLOW_PARENT = "OVERFLOW_PARENT"      # a box extends outside its parent beyond the tolerance
OVERFLOW_PAGE = "OVERFLOW_PAGE"          # a box extends outside the page
OVERLAP = "OVERLAP"                      # two siblings overlap more than the allowed ratio
MISALIGNED = "MISALIGNED"                # near-aligned siblings that are not exactly aligned
UNEVEN_SPACING = "UNEVEN_SPACING"        # a repeated group whose pitch is not uniform
TEXT_OVERFLOW = "TEXT_OVERFLOW"          # estimated text is wider than its box
TEXT_CLIPPED = "TEXT_CLIPPED"            # the line box is taller than the component
LOW_CONTRAST = "LOW_CONTRAST"            # text/background contrast below the WCAG AA ratio
TOUCH_TARGET_SMALL = "TOUCH_TARGET_SMALL"  # a control is smaller than the minimum size
FONT_TOO_SMALL = "FONT_TOO_SMALL"        # font size below the minimum
# --- functional / interactive codes (functional_metrics.py) ---
OCCLUDED_INTERACTIVE = "OCCLUDED_INTERACTIVE"  # interactive element is fully hidden by another
FORM_NO_SUBMIT = "FORM_NO_SUBMIT"              # container has inputs but no submit button
FOCUS_ORDER_MISMATCH = "FOCUS_ORDER_MISMATCH"  # tab order does not match reading order
NO_INTERACTIVE_ELEMENTS = "NO_INTERACTIVE_ELEMENTS"  # design has no actionable controls

ALL_CODES = (
    OVERFLOW_PARENT, OVERFLOW_PAGE, OVERLAP, MISALIGNED, UNEVEN_SPACING, TEXT_OVERFLOW,
    TEXT_CLIPPED, LOW_CONTRAST, TOUCH_TARGET_SMALL, FONT_TOO_SMALL,
    OCCLUDED_INTERACTIVE, FORM_NO_SUBMIT, FOCUS_ORDER_MISMATCH, NO_INTERACTIVE_ELEMENTS,
)

SEVERITY = {
    OVERFLOW_PARENT: "error", OVERFLOW_PAGE: "error", OVERLAP: "warning", MISALIGNED: "warning",
    UNEVEN_SPACING: "warning", TEXT_OVERFLOW: "warning", TEXT_CLIPPED: "warning",
    LOW_CONTRAST: "warning", TOUCH_TARGET_SMALL: "warning", FONT_TOO_SMALL: "info",
    OCCLUDED_INTERACTIVE: "error", FORM_NO_SUBMIT: "warning",
    FOCUS_ORDER_MISMATCH: "info", NO_INTERACTIVE_ELEMENTS: "info",
}

UNIT = {
    OVERFLOW_PARENT: "px", OVERFLOW_PAGE: "px", OVERLAP: "ratio", MISALIGNED: "px",
    UNEVEN_SPACING: "px", TEXT_OVERFLOW: "px", TEXT_CLIPPED: "px", LOW_CONTRAST: "ratio_shortfall",
    TOUCH_TARGET_SMALL: "px", FONT_TOO_SMALL: "px",
    OCCLUDED_INTERACTIVE: "ratio", FORM_NO_SUBMIT: "count",
    FOCUS_ORDER_MISMATCH: "count", NO_INTERACTIVE_ELEMENTS: "count",
}


@dataclass(frozen=True)
class Issue:
    """One measurable problem. ``measure`` is its size in ``unit`` (always > 0)."""

    code: str
    component_ids: tuple[str, ...]
    message: str
    measure: float
    discriminator: str = ""  # e.g. the edge name, to tell two issues on one component apart
    details: dict[str, float | str] = field(default_factory=dict, compare=False, hash=False)

    @property
    def key(self) -> str:
        """Stable identity across re-evaluations (the same problem has the same key)."""
        return f"{self.code}:{','.join(self.component_ids)}:{self.discriminator}"

    @property
    def severity(self) -> str:
        return SEVERITY[self.code]

    @property
    def unit(self) -> str:
        return UNIT[self.code]

    def to_dict(self) -> dict:
        return {
            "key": self.key, "code": self.code, "severity": self.severity,
            "components": list(self.component_ids), "message": self.message,
            "measure": round(self.measure, 3), "unit": self.unit,
            "details": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.details.items()},
        }
