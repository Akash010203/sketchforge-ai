"""Run every check on a document and return one structured result."""

from __future__ import annotations

from dataclasses import dataclass, field

from sketchforge.design_ir.constraints import LayoutConstraints
from sketchforge.design_ir.schema import DesignDocument
from sketchforge.evaluation import issues as I  # noqa: E741
from sketchforge.evaluation.geometry_metrics import Fidelity, fidelity
from sketchforge.evaluation.issues import Issue
from sketchforge.evaluation.layout_metrics import detect_layout_issues
from sketchforge.evaluation.text_metrics import check_text


@dataclass
class EvaluationResult:
    issues: list[Issue]
    metrics: dict[str, float]
    fidelity: Fidelity | None = None
    notes: list[str] = field(default_factory=list)

    def by_code(self, code: str) -> list[Issue]:
        return [i for i in self.issues if i.code == code]

    def count(self, code: str) -> int:
        return len(self.by_code(code))

    def magnitude(self, code: str) -> float:
        """Sum of the measures of all issues with this code (px, or ratio for OVERLAP/CONTRAST)."""
        return sum(i.measure for i in self.by_code(code))

    def keys(self) -> set[str]:
        return {i.key for i in self.issues}

    def issue(self, key: str) -> Issue | None:
        return next((i for i in self.issues if i.key == key), None)

    def to_dict(self) -> dict:
        return {
            "metrics": {k: round(v, 4) for k, v in sorted(self.metrics.items())},
            "issues": [i.to_dict() for i in self.issues],
            "notes": list(self.notes),
        }


def evaluate_document(doc: DesignDocument, constraints: LayoutConstraints | None = None) -> EvaluationResult:
    c = constraints or LayoutConstraints()
    issues = [*detect_layout_issues(doc, c), *check_text(doc, c)]
    issues.sort(key=lambda i: (i.code, i.component_ids, i.discriminator))
    metrics: dict[str, float] = {
        "components": float(len(doc.components) - 1),
        "issues_total": float(len(issues)),
    }
    for sev in ("error", "warning", "info"):
        metrics[f"issues_{sev}"] = float(sum(1 for i in issues if i.severity == sev))
    for code in I.ALL_CODES:
        mine = [i for i in issues if i.code == code]
        metrics[f"count.{code}"] = float(len(mine))
        metrics[f"magnitude.{code}"] = round(sum(i.measure for i in mine), 4)
    for comp in doc.components:
        if comp.id != doc.root_id:
            key = f"components.{comp.type.value}"
            metrics[key] = metrics.get(key, 0.0) + 1.0
    fid = fidelity(doc)
    notes: list[str] = []
    if fid is not None:
        metrics.update(fid.as_dict())
    else:
        notes.append("no sketch provenance: fidelity metrics skipped")
    return EvaluationResult(issues, metrics, fid, notes)
