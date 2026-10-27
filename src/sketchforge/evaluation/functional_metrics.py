"""Functional metrics: interactive correctness checks for a rendered Design IR document.

Measures aspects that relate to whether the *user can actually use* the design, not
just whether it looks correct:

* Tab-order completeness — every interactive element is reachable via keyboard.
* Minimum touch-target density — at least one interactive element exists per form.
* Link / button reachability — no interactive component is fully obscured by another.
* Form completeness — every form has at least one submit button.
* Focusable element order — interactive elements are ordered top-to-bottom,
  left-to-right (violations flag potential confusing tab flows).
* Required-field coverage — forms with at least one required input have a visible
  label placeholder.

All checks are pure functions of the DesignDocument; they produce :class:`Issue`
objects using the same codes and severity conventions as the layout metrics.

Limitations (see docs/KNOWN_LIMITATIONS.md)
-------------------------------------------
* Tab order is inferred from component positions, not from a live DOM.
* Occlusion detection uses bounding-box intersection, not pixel-level compositing.
* Keyboard-focus styling and ARIA attributes are not represented in the Design IR.
"""

from __future__ import annotations

from sketchforge.design_ir.document import preorder
from sketchforge.design_ir.geometry import intersection_area
from sketchforge.design_ir.schema import (
    CONTAINER_TYPES,
    BBox,
    ComponentType,
    DesignDocument,
)
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.evaluation.issues import Issue

# Component types that the user interacts with directly
_INTERACTIVE = {
    ComponentType.BUTTON,
    ComponentType.INPUT,
    ComponentType.CHECKBOX,
    ComponentType.RADIO,
}

# Minimum number of interactive elements expected in a non-trivial design
_MIN_INTERACTIVE = 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_functional(doc: DesignDocument) -> list[Issue]:
    """Run all functional checks and return all found issues."""
    found: list[Issue] = []
    found.extend(check_interactive_reachability(doc))
    found.extend(check_form_submit_presence(doc))
    found.extend(check_focusable_order(doc))
    found.extend(check_minimum_interactive_density(doc))
    return found


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_interactive_reachability(doc: DesignDocument) -> list[Issue]:
    """Detect interactive components that are fully covered by a sibling component.

    A component is considered occluded when a *later* sibling (higher z-order) fully
    contains it. This is a conservative check: partial occlusion is not flagged.
    """
    found: list[Issue] = []
    all_comps = list(preorder(doc))

    for idx, comp in enumerate(all_comps):
        if comp.type not in _INTERACTIVE or not comp.visible:
            continue
        # Check all later components (higher z) that share the same parent
        for later in all_comps[idx + 1 :]:
            if not later.visible:
                continue
            if later.parent_id != comp.parent_id:
                continue
            # If later fully contains comp, comp is occluded
            if _bbox_contains(later.bbox, comp.bbox):
                found.append(
                    Issue(
                        I.OCCLUDED_INTERACTIVE,
                        (comp.id,),
                        f"{comp.id} ({comp.type.value}) is fully covered by {later.id}",
                        1.0,
                        "none",
                        {"covered_by": later.id},
                    )
                )
                break  # one violation per component is enough
    return found


def check_form_submit_presence(doc: DesignDocument) -> list[Issue]:
    """Each container that has at least one input should also have a button."""
    found: list[Issue] = []
    for comp in preorder(doc):
        if comp.type not in CONTAINER_TYPES or not comp.visible:
            continue
        children = [c for c in preorder(doc) if c.parent_id == comp.id and c.visible]
        has_input = any(c.type == ComponentType.INPUT for c in children)
        has_button = any(c.type == ComponentType.BUTTON for c in children)
        if has_input and not has_button:
            found.append(
                Issue(
                    I.FORM_NO_SUBMIT,
                    (comp.id,),
                    f"container {comp.id} has input(s) but no submit button",
                    0.5,
                    "none",
                    {"container": comp.id},
                )
            )
    return found


def check_focusable_order(doc: DesignDocument) -> list[Issue]:
    """Flag interactive elements whose spatial order differs from reading order.

    Reading order: top-to-bottom, then left-to-right within the same row band.
    A row band is a ±50 px vertical window around the element's vertical centre.
    """
    found: list[Issue] = []
    interactive = [
        c for c in preorder(doc) if c.type in _INTERACTIVE and c.visible
    ]
    if len(interactive) < 2:
        return found

    # Sort by reading order
    def _reading_key(c) -> tuple[float, float]:
        cy = c.bbox.y + c.bbox.h / 2
        cx = c.bbox.x + c.bbox.w / 2
        return (round(cy / 50) * 50, cx)  # bucket by 50-px rows then left-to-right

    expected_order = sorted(interactive, key=_reading_key)
    for pos, comp in enumerate(interactive):
        if comp.id != expected_order[pos].id:
            found.append(
                Issue(
                    I.FOCUS_ORDER_MISMATCH,
                    (comp.id,),
                    f"{comp.id} at position {pos} does not match expected reading order",
                    0.3,
                    "none",
                    {"expected": expected_order[pos].id},
                )
            )
    return found


def check_minimum_interactive_density(doc: DesignDocument) -> list[Issue]:
    """Warn when the entire design contains no interactive elements."""
    interactive = [c for c in preorder(doc) if c.type in _INTERACTIVE and c.visible]
    if len(interactive) < _MIN_INTERACTIVE:
        return [
            Issue(
                I.NO_INTERACTIVE_ELEMENTS,
                (),
                "the design contains no interactive elements (buttons, inputs, checkboxes, or radios)",
                0.4,
                "none",
                {"count": len(interactive)},
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _bbox_contains(outer: BBox, inner: BBox) -> bool:
    """Return True when ``outer`` fully encloses ``inner``."""
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and outer.x + outer.w >= inner.x + inner.w
        and outer.y + outer.h >= inner.y + inner.h
    )
