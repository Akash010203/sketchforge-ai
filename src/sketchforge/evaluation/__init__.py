"""Measurement: detection accuracy, layout/text/fidelity metrics, pixel metrics and reports."""

from sketchforge.evaluation.evaluator import EvaluationResult, evaluate_document
from sketchforge.evaluation.issues import Issue

__all__ = ["EvaluationResult", "Issue", "evaluate_document"]
