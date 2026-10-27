"""Tiered NVIDIA Nemotron Multi-Model Router.

Directly implements the hackathon's recommended model tiering architecture:
- Nemotron-3-Ultra-550b-a55b: Heavy reasoning, AppSpec planning & DB architecture.
- Nemotron-3_5-Lightning: High-throughput full-stack code synthesis.
- NVIDIA-Nemotron-3-Nano-30B-A3B: Fast surgical repairs & natural language micro-edits.
- Nemotron-3.5-Super-VL: Multimodal visual sketch perception.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NemotronTier:
    PLANNER = "nvidia/Nemotron-3-Ultra-550b-a55b"
    CODER = "nvidia/Nemotron-3_5-Lightning"
    REPAIR = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    VISION = "nvidia/Nemotron-3.5-Super-VL"
    SUPER_120B = "nvidia/nemotron-3-super-120b-a12b"


class ModelRouter:
    """Routes generation, repair, and perception tasks to optimal Nemotron tiers."""

    def __init__(self, nebius_client: Any = None) -> None:
        self.client = nebius_client
        self.planner_model = os.environ.get("NEMOTRON_TIER_PLANNER", NemotronTier.PLANNER)
        self.coder_model = os.environ.get("NEMOTRON_TIER_CODER", NemotronTier.CODER)
        self.repair_model = os.environ.get("NEMOTRON_TIER_REPAIR", NemotronTier.REPAIR)
        self.vision_model = os.environ.get("NEMOTRON_TIER_VISION", NemotronTier.VISION)

    def route_for_task(self, task: str) -> str:
        """Select appropriate model based on computational complexity."""
        task_norm = task.lower()
        if "plan" in task_norm or "architect" in task_norm or "schema" in task_norm:
            # Fall back to Lightning if Ultra exceeds quota/latency limits
            return self.planner_model
        elif "repair" in task_norm or "patch" in task_norm or "micro_edit" in task_norm:
            return self.repair_model
        elif "vision" in task_norm or "multimodal" in task_norm:
            return self.vision_model
        return self.coder_model

    def describe_tiers(self) -> dict[str, str]:
        return {
            "Architecture & System Planning": self.planner_model,
            "Full-Stack Code Synthesis": self.coder_model,
            "Surgical Discrepancy Repair": self.repair_model,
            "Multimodal Sketch Perception": self.vision_model,
        }
