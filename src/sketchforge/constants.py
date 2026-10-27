"""Project-wide constants. Anything tunable lives in config/*.yaml instead."""

from __future__ import annotations

SCHEMA_VERSION = "1.0.0"
"""Design IR schema version. Bump with a registered migration in design_ir/migrations.py."""

PIPELINE_VERSION = "heuristic-0.1"
"""Identifies the deterministic OpenCV detection pipeline that produced a document."""

SUPPORTED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"})

# Component types that carry user-visible text.
TEXT_BEARING_TYPES = frozenset({"text", "heading", "button", "input", "checkbox", "radio"})

# Component types a user can interact with (used for touch-size constraints).
INTERACTIVE_TYPES = frozenset({"button", "input", "checkbox", "radio"})

DEFAULT_FONT_FAMILY = "Inter, 'Helvetica Neue', Arial, sans-serif"
