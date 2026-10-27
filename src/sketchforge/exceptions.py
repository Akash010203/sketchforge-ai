"""Exception hierarchy. Every error SketchForge raises on purpose derives from SketchForgeError."""

from __future__ import annotations


class SketchForgeError(Exception):
    """Base class for all expected, user-reportable errors."""


class ConfigError(SketchForgeError):
    """Configuration file is missing required values or contains invalid ones."""


class ImageLoadError(SketchForgeError):
    """The image could not be validated or decoded safely."""


class PreprocessingError(SketchForgeError):
    """Preprocessing could not produce a usable ink mask."""


class DetectionError(SketchForgeError):
    """Detection or layout inference failed."""


class MigrationError(SketchForgeError):
    """A Design IR document could not be migrated to the current schema."""


class DesignValidationError(SketchForgeError):
    """A Design IR document violates the schema or structural rules."""

    def __init__(self, message: str, report: object | None = None) -> None:
        super().__init__(message)
        self.report = report


class RenderError(SketchForgeError):
    """A design could not be rendered."""


class AssetError(SketchForgeError):
    """An image asset could not be validated, stored, or retrieved."""


class EditError(SketchForgeError):
    """An edit command was invalid or could not be applied."""


class RepairError(SketchForgeError):
    """The repair engine could not build or apply a patch."""


class WorkflowError(SketchForgeError):
    """A workflow step failed or the workflow state is inconsistent."""


class BudgetExceededError(WorkflowError):
    """A time or iteration budget ran out."""
