"""Logging configuration: YAML dictConfig with a safe fallback."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path

import yaml

from sketchforge.utilities.paths import repo_root


def setup_logging(config_path: str | Path | None = None, level: int | None = None) -> None:
    path = Path(config_path) if config_path else repo_root() / "config" / "logging.yaml"
    try:
        with open(path, encoding="utf-8") as handle:
            logging.config.dictConfig(yaml.safe_load(handle))
    except (OSError, ValueError, yaml.YAMLError):
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
        )
    if level is not None:
        logging.getLogger("sketchforge").setLevel(level)
