"""Predefined layout constraints and the regression policy.

These thresholds are the *definition* of "a layout problem" for the evaluator and the repair
engine. They load from config/evaluation.yaml; the defaults below match that file.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LayoutConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    containment_tolerance_px: float = Field(2.0, ge=0)
    overlap_tolerance_ratio: float = Field(0.05, ge=0, le=1)
    align_snap_radius_px: float = Field(16.0, gt=0)
    align_tolerance_px: float = Field(2.0, ge=0)
    spacing_tolerance_px: float = Field(4.0, ge=0)
    min_touch_size_px: float = Field(24.0, ge=0)
    min_control_size_px: float = Field(16.0, ge=0)
    min_contrast_ratio: float = Field(4.5, ge=1.0)
    text_overflow_tolerance_px: float = Field(1.0, ge=0)
    min_font_size_px: float = Field(10.0, ge=1)
    page_margin_tolerance_px: float = Field(1.0, ge=0)


class RegressionPolicy(BaseModel):
    """What a repair may not make worse, and how much the target metric must improve."""

    model_config = ConfigDict(extra="forbid")

    max_fidelity_iou_drop: float = Field(0.02, ge=0)
    max_position_error_increase_px: float = Field(2.0, ge=0)
    min_target_improvement: float = Field(0.01, ge=0)
