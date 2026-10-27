"""Training report: JSON + Markdown summary of a completed training run."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from sketchforge.training.metrics import EpochMetrics


@dataclass
class TrainingReport:
    model_name: str
    config: dict
    epochs: list[EpochMetrics] = field(default_factory=list)
    best_val_loss: float = float("inf")
    best_val_map: float = -1.0
    best_epoch: int = 0
    final_test_metrics: EpochMetrics | None = None
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    finished_at: str = ""
    stopped_early: bool = False
    baseline_comparison: dict | None = None   # vs. OpenCV heuristic baseline

    def add_epoch(self, m: EpochMetrics) -> None:
        self.epochs.append(m)
        if m.phase == "val" and m.loss < self.best_val_loss:
            self.best_val_loss = m.loss
        if m.phase == "val" and m.mAP25 > self.best_val_map:
            self.best_val_map = m.mAP25
            self.best_epoch = m.epoch

    def finish(self, test: EpochMetrics | None = None, stopped_early: bool = False) -> None:
        self.final_test_metrics = test
        self.stopped_early = stopped_early
        self.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stopped_early": self.stopped_early,
            "best_epoch": self.best_epoch,
            "best_val_loss": round(self.best_val_loss, 6),
            "best_val_mAP": round(self.best_val_map, 6),
            "selection_metric": "mAP@0.25 (validation box loss until AP is nonzero)",
            "test": self.final_test_metrics.to_dict() if self.final_test_metrics else None,
            "epochs": [e.to_dict() for e in self.epochs],
            "config": self.config,
            "baseline_comparison": self.baseline_comparison,
        }

    def save(self, directory: Path) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / f"{self.model_name}_report.json"
        md_path   = directory / f"{self.model_name}_report.md"
        json_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        return json_path, md_path

    def to_markdown(self) -> str:
        test = self.final_test_metrics
        lines = [
            f"# Training Report: {self.model_name}",
            f"",
            f"| | |",
            f"|---|---|",
            f"| Started | {self.started_at} |",
            f"| Finished | {self.finished_at} |",
            f"| Best epoch | {self.best_epoch} |",
            f"| Best val loss | {self.best_val_loss:.6f} |",
            f"| Best val mAP@0.25 | {self.best_val_map:.4f} |",
            f"| Stopped early | {self.stopped_early} |",
            f"",
        ]
        if test:
            lines += [
                f"## Test metrics",
                f"",
                f"- Loss: `{test.loss:.4f}`",
                f"- Accuracy: `{test.accuracy:.4f}`",
                f"- Mean IoU: `{test.mean_iou:.4f}`",
                f"- mAP: `{test.mAP:.4f}`",
                f"",
            ]
        if self.baseline_comparison:
            lines += [
                f"## Baseline comparison (vs. OpenCV heuristics)",
                f"",
                f"| Metric | Heuristic | Trained |",
                f"|---|---|---|",
            ]
            for k, v in self.baseline_comparison.items():
                lines.append(f"| {k} | {v.get('heuristic', '—')} | {v.get('trained', '—')} |")
            lines.append("")
        lines += [
            f"## Epoch log",
            f"",
            f"| Epoch | Phase | Loss | Accuracy | IoU | mAP | s |",
            f"|---|---|---|---|---|---|---|",
        ]
        for e in self.epochs[-30:]:  # last 30 rows
            lines.append(
                f"| {e.epoch} | {e.phase} | {e.loss:.4f} | {e.accuracy:.3f} "
                f"| {e.mean_iou:.3f} | {e.mAP:.3f} | {e.duration_s:.1f} |"
            )
        return "\n".join(lines) + "\n"
