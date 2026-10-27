"""Heuristic scores and uncertainty bookkeeping.

IMPORTANT: ``type_scores`` are *heuristic, uncalibrated* rule scores normalized to sum to 1. They
are useful for ranking and for flagging ambiguity; they are not probabilities and must not be
reported as accuracy. Measured accuracy lives in the evaluation reports.
"""

from __future__ import annotations

AMBIGUITY_RATIO = 0.75  # second-best score >= 75% of the best => flag as ambiguous


def normalize_scores(raw: dict[str, float]) -> dict[str, float]:
    positive = {k: v for k, v in raw.items() if v > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    return {k: round(v / total, 4) for k, v in sorted(positive.items(), key=lambda kv: -kv[1])}


def best_and_ambiguity(raw: dict[str, float]) -> tuple[str, float, bool]:
    """Return (best type, its raw score, whether the runner-up is close enough to be ambiguous)."""
    ranked = sorted(raw.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    ambiguous = len(ranked) > 1 and ranked[1][1] >= AMBIGUITY_RATIO * best_score
    return best, best_score, ambiguous


def combine_confidence(rule_score: float, geometric_confidence: float) -> float:
    """Overall confidence = how strongly a rule fired x how clean the underlying geometry was."""
    return round(max(0.05, min(0.99, rule_score * geometric_confidence)), 4)
