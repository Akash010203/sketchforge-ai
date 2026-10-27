"""Before/after repair report: structured (JSON) and readable (Markdown).

The outcome vocabulary keeps apart things that are easy to conflate: a change that was *made*,
a change that *measurably improved* the design, one that made it worse, one that made no
measurable difference, and a run whose result could not be verified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from sketchforge.evaluation.evaluator import EvaluationResult
from sketchforge.utilities.paths import atomic_write_bytes, atomic_write_text, ensure_dir

if TYPE_CHECKING:
    from sketchforge.repair.patch import PatchRecord


class Outcome(str, Enum):
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    NO_MEASURABLE_DIFFERENCE = "NO_MEASURABLE_DIFFERENCE"
    UNABLE_TO_VERIFY = "UNABLE_TO_VERIFY"


def classify_outcome(initial: EvaluationResult, final: EvaluationResult) -> Outcome:
    """IMPROVED/REGRESSED by (errors, issue count, total issue size), compared in that order."""
    def rank(r: EvaluationResult) -> tuple[float, float]:
        return (r.metrics["issues_error"], r.metrics["issues_total"])

    a, b = rank(initial), rank(final)
    if b < a:
        return Outcome.IMPROVED
    if b > a:
        return Outcome.REGRESSED
    size = lambda r: round(sum(i.measure for i in r.issues), 3)  # noqa: E731
    if size(final) < size(initial) - 1e-6:
        return Outcome.IMPROVED
    if size(final) > size(initial) + 1e-6:
        return Outcome.REGRESSED
    return Outcome.NO_MEASURABLE_DIFFERENCE


@dataclass
class RepairReport:
    outcome: Outcome
    initial: EvaluationResult
    final: EvaluationResult
    records: list[PatchRecord]
    stop_reason: str
    hash_before: str
    hash_after: str
    injection: dict | None = None
    notes: list[str] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    images: dict[str, np.ndarray] = field(default_factory=dict)  # not serialised into JSON

    # ------------------------------------------------------------------ derived
    @property
    def accepted(self) -> list[PatchRecord]:
        return [r for r in self.records if r.accepted]

    @property
    def rejected(self) -> list[PatchRecord]:
        return [r for r in self.records if not r.accepted]

    @property
    def resolved_keys(self) -> list[str]:
        return sorted(self.initial.keys() - self.final.keys())

    @property
    def remaining_keys(self) -> list[str]:
        return sorted(self.initial.keys() & self.final.keys())

    @property
    def introduced_keys(self) -> list[str]:
        return sorted(self.final.keys() - self.initial.keys())

    def headline(self) -> str:
        i, f = self.initial.metrics, self.final.metrics
        return (f"{self.outcome.value}: issues {int(i['issues_total'])} -> {int(f['issues_total'])} "
                f"(errors {int(i['issues_error'])} -> {int(f['issues_error'])}); "
                f"{len(self.accepted)} patch(es) accepted, {len(self.rejected)} rejected")

    # ------------------------------------------------------------------ output
    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "headline": self.headline(),
            "injection": self.injection,
            "initial": self.initial.to_dict(),
            "final": self.final.to_dict(),
            "resolved": self.resolved_keys,
            "remaining": self.remaining_keys,
            "introduced": self.introduced_keys,
            "attempts": [r.to_dict() for r in self.records],
            "stop_reason": self.stop_reason,
            "limits": self.limits,
            "document_hash_before": self.hash_before,
            "document_hash_after": self.hash_after,
            "duration_ms": round(self.duration_ms, 2),
            "notes": list(self.notes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        i, f = self.initial.metrics, self.final.metrics
        lines = ["# SketchForge repair report", "", f"**{self.headline()}**", ""]
        if self.injection:
            lines += ["## Injected fault", "",
                      f"- kind: `{self.injection['kind']}` on {', '.join(self.injection['components'])}",
                      f"- {self.injection['description']}",
                      f"- expected evaluator finding: `{self.injection['expected_issue']}`", ""]
        lines += ["## Metrics before and after", "", "| metric | before | after |", "|---|---:|---:|"]
        keys = ["issues_total", "issues_error", "issues_warning", "issues_info"]
        keys += sorted(k for k in i if k.startswith("magnitude.") and (i[k] or f.get(k)))
        keys += [k for k in ("fidelity_mean_iou", "position_error_mean_px", "position_error_max_px") if k in i]
        for k in keys:
            lines.append(f"| {k} | {i.get(k, 0):g} | {f.get(k, 0):g} |")
        lines += ["", "## Attempts", ""]
        if not self.records:
            lines.append("No patches were attempted.")
        else:
            lines += ["| # | issue | strategy | target before -> after | decision | why |", "|---|---|---|---|---|---|"]
            for r in self.records:
                after = "n/a" if r.target_after is None else f"{r.target_after:.2f}"
                lines.append(f"| {r.iteration} | `{r.patch.issue_key}` | {r.patch.strategy}{(' / ' + r.patch.variant) if r.patch.variant else ''} | "
                             f"{r.target_before:.2f} -> {after} | **{r.decision}** | {r.reason} |")
        for r in self.accepted:
            lines += ["", f"### Accepted: `{r.patch.issue_key}`", "", f"- reason: {r.patch.reason}",
                      f"- expected: {r.patch.expected}"]
            for ch in r.patch.changes:
                lines.append(f"- `{ch.component_id}` {ch.property}: `{ch.original}` -> `{ch.proposed}`")
            if r.visual:
                lines.append(f"- visual footprint: {r.visual.get('changed_pixel_ratio', 0):.2%} of pixels changed, "
                             f"SSIM {r.visual.get('ssim', 1):.4f}")
            lines.append(f"- regression check: {'; '.join(r.regression.get('reasons', []))}")
        lines += ["", "## Remaining issues", ""]
        if not self.final.issues:
            lines.append("None.")
        else:
            lines += [f"- `{x.key}` — {x.message}" for x in self.final.issues]
        if self.introduced_keys:
            lines += ["", f"Issues present after but not before: {', '.join(f'`{k}`' for k in self.introduced_keys)}"]
        lines += ["", "## Run", "", f"- stopped because: {self.stop_reason}",
                  f"- limits: {json.dumps(self.limits)}", f"- duration: {self.duration_ms:.0f} ms",
                  f"- document hash: `{self.hash_before[:12]}` -> `{self.hash_after[:12]}`"]
        for note in self.notes:
            lines.append(f"- note: {note}")
        lines += ["", "## How to read this", "",
                  "Measurements are structural and geometric (box containment, alignment, spacing, "
                  "estimated text fit, WCAG contrast). A better score means fewer measurable layout "
                  "problems, not that the design is semantically correct or visually pleasing. Text "
                  "width uses an estimate, not a font engine."]
        return "\n".join(lines) + "\n"

    def save(self, directory: str | Path, stem: str = "repair_report") -> dict[str, Path]:
        import cv2

        out = ensure_dir(directory)
        paths = {"json": out / f"{stem}.json", "markdown": out / f"{stem}.md"}
        atomic_write_text(paths["json"], self.to_json())
        atomic_write_text(paths["markdown"], self.to_markdown())
        for name, image in self.images.items():
            ok, buf = cv2.imencode(".png", image)
            if ok:
                paths[name] = atomic_write_bytes(out / f"{stem}_{name}.png", buf.tobytes())
        return paths
