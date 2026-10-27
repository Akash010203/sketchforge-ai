"""Configuration loading.

Defaults live in the pydantic models below, so the application and the tests work without any
YAML file. ``config/app.yaml`` and ``config/evaluation.yaml`` override them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sketchforge.design_ir.constraints import LayoutConstraints, RegressionPolicy
from sketchforge.exceptions import ConfigError
from sketchforge.utilities.paths import repo_root


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisionConfig(_Section):
    max_file_bytes: int = Field(25 * 1024 * 1024, gt=0)
    max_pixels: int = Field(60_000_000, gt=0)
    min_side_px: int = Field(64, ge=1)
    max_side_px: int = Field(12_000, ge=64)
    working_long_side: int = Field(1024, ge=256, le=4096)
    min_component_side_px: int = Field(10, ge=2)
    design_width_landscape: int = Field(1024, ge=200)
    design_width_portrait: int = Field(414, ge=200)


class WorkflowConfig(_Section):
    max_repair_iterations: int = Field(6, ge=1, le=50)
    repair_time_budget_seconds: float = Field(20.0, gt=0)
    max_attempts_per_failure: int = Field(3, ge=1, le=3)
    no_progress_window: int = Field(4, ge=1)


class PathsConfig(_Section):
    output_dir: str = "output"
    projects_dir: str = "output/projects"


class AppConfig(_Section):
    vision: VisionConfig = Field(default_factory=VisionConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    constraints: LayoutConstraints = Field(default_factory=LayoutConstraints)
    regression: RegressionPolicy = Field(default_factory=RegressionPolicy)

    def resolve_path(self, relative: str) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else repo_root() / p


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return data


def load_config(config_dir: str | Path | None = None) -> AppConfig:
    """Load and validate configuration; unknown keys are rejected so typos do not pass silently."""
    root = Path(config_dir) if config_dir else repo_root() / "config"
    merged: dict[str, Any] = {}
    merged.update(_read_yaml(root / "app.yaml"))
    merged.update(_read_yaml(root / "evaluation.yaml"))
    try:
        return AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {root}: {exc}") from exc
