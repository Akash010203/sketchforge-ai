"""Interaction declarations attached to components."""

from __future__ import annotations

from typing import Literal

from sketchforge.domain.base import StrictModel

class Interaction(StrictModel):
    event: Literal["click", "submit", "change", "hover"] = "click"
    action: Literal["none", "navigate", "submit_form", "toggle", "open_modal"] = "none"
    target: str | None = None
    inferred: bool = True
