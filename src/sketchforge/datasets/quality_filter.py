"""Quality filtering for raw dataset samples.

Each RawSample arriving from a source adapter is scored against a set of
configurable heuristic checks.  Samples that fail any *hard* check are
rejected outright.  Samples that fail one or more *soft* checks are flagged in
FilterResult.warnings but still allowed through (unless ``strict=True``).

Design
------
* Stateless functions: all logic is implemented as pure functions so callers
  can compose them freely without class instantiation.
* FilterResult: a lightweight dataclass pairing the pass/fail verdict with
  actionable diagnostics.
* No hard dependency on PIL/cv2: dimension and aspect-ratio checks degrade
  gracefully when image-processing libraries are absent.

Typical usage::

    from sketchforge.datasets.quality_filter import filter_samples, FilterConfig

    config = FilterConfig(min_image_width=64, min_html_bytes=20)
    kept, rejected = filter_samples(raw_samples, config=config)

Section 3 spec checklist
-------------------------
* Minimum image dimensions (width x height).
* Minimum HTML / label byte length.
* Aspect-ratio sanity check.
* Non-empty bounding-box requirement (optional; disabled by default).
* Maximum duplicate HTML ratio within a batch (soft check).
* Source-dataset allow-list: reject samples from any unlisted adapter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Sequence

log = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    """Configurable thresholds for all quality checks.

    Parameters
    ----------
    min_image_width:
        Reject samples whose image is narrower than this in pixels.
        Set to 0 to disable.
    min_image_height:
        Reject samples whose image is shorter than this in pixels.
        Set to 0 to disable.
    min_html_bytes:
        Reject samples whose HTML/label payload is shorter than this.
        Set to 0 to disable.
    max_aspect_ratio:
        Reject images with ``max(w, h) / min(w, h)`` exceeding this value.
        Catches pathological 1x10000 images.  Set to 0 to disable.
    require_bboxes:
        When True, reject any sample with an empty bounding-box list.
    allowed_sources:
        If non-empty, reject samples whose ``source_dataset`` is not in
        this set.  Leave empty to allow all sources.
    max_html_duplicate_ratio:
        Soft-check threshold: if more than this fraction of the batch shares
        identical HTML content, flag a warning.  Set to 1.0 to disable.
    strict:
        When True, soft-check failures are treated as hard failures and
        cause the sample to be rejected.
    """

    min_image_width: int = 32
    min_image_height: int = 32
    min_html_bytes: int = 10
    max_aspect_ratio: float = 20.0
    require_bboxes: bool = False
    allowed_sources: set = field(default_factory=set)
    max_html_duplicate_ratio: float = 0.8
    strict: bool = False


@dataclass
class FilterResult:
    """Outcome of running all quality checks against one RawSample.

    Attributes
    ----------
    passed:
        True when no hard check failed (and strict=False or no soft
        checks failed either).
    sample_id:
        Identifies the sample for logging.
    hard_failures:
        List of human-readable strings naming each failed hard check.
    warnings:
        List of human-readable strings naming each failed soft check.
    """

    passed: bool
    sample_id: str
    hard_failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


def check_image_dimensions(sample, config: FilterConfig) -> list:
    """Return a list of dimension-related failure strings (empty = pass)."""
    if config.min_image_width <= 0 and config.min_image_height <= 0:
        return []

    path = sample.image_path
    if path is None:
        # Byte-backed or URL-only sample: skip dimension check.
        return []

    try:
        import cv2  # type: ignore[import]

        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return ["image_unreadable"]
        h, w = img.shape[:2]
    except ImportError:
        try:
            from PIL import Image  # type: ignore[import]

            with Image.open(path) as im:
                w, h = im.size
        except ImportError:
            log.debug(
                "Neither cv2 nor PIL available - skipping dimension check for %s",
                path.name,
            )
            return []
        except Exception as exc:  # noqa: BLE001
            log.debug("PIL could not open %s: %s", path.name, exc)
            return ["image_unreadable"]
    except Exception as exc:  # noqa: BLE001
        log.debug("cv2 could not read %s: %s", path.name, exc)
        return ["image_unreadable"]

    failures: list = []
    if config.min_image_width > 0 and w < config.min_image_width:
        failures.append(f"width_{w}<{config.min_image_width}")
    if config.min_image_height > 0 and h < config.min_image_height:
        failures.append(f"height_{h}<{config.min_image_height}")
    if config.max_aspect_ratio > 0 and min(w, h) > 0:
        ratio = max(w, h) / min(w, h)
        if ratio > config.max_aspect_ratio:
            failures.append(f"aspect_ratio_{ratio:.1f}>{config.max_aspect_ratio}")
    return failures


def check_html_length(sample, config: FilterConfig) -> list:
    """Reject if both HTML and label are shorter than min_html_bytes."""
    if config.min_html_bytes <= 0:
        return []

    content = sample.html or sample.label or ""
    if len(content.encode("utf-8")) < config.min_html_bytes:
        return [f"html_too_short_{len(content)}B<{config.min_html_bytes}B"]
    return []


def check_bboxes(sample, config: FilterConfig) -> list:
    """Reject if require_bboxes is set and bounding-box list is empty."""
    if config.require_bboxes and not sample.bboxes:
        return ["no_bboxes"]
    return []


def check_source_allowlist(sample, config: FilterConfig) -> list:
    """Reject if allowed_sources is non-empty and sample is not in it."""
    if config.allowed_sources and sample.source_dataset not in config.allowed_sources:
        return [f"source_not_allowed:{sample.source_dataset}"]
    return []


# ---------------------------------------------------------------------------
# Per-sample quality check
# ---------------------------------------------------------------------------


def evaluate_sample(sample, config: "FilterConfig | None" = None) -> FilterResult:
    """Run all quality checks against a single sample.

    Parameters
    ----------
    sample:
        A RawSample instance from source_adapters.
    config:
        Quality thresholds.  Uses FilterConfig defaults when omitted.

    Returns
    -------
    FilterResult
    """
    if config is None:
        config = FilterConfig()

    hard: list = []
    hard.extend(check_image_dimensions(sample, config))
    hard.extend(check_html_length(sample, config))
    hard.extend(check_bboxes(sample, config))
    hard.extend(check_source_allowlist(sample, config))

    return FilterResult(
        passed=len(hard) == 0,
        sample_id=sample.sample_id,
        hard_failures=hard,
    )


# ---------------------------------------------------------------------------
# Batch filter
# ---------------------------------------------------------------------------


def filter_samples(
    samples: Iterable,
    config: "FilterConfig | None" = None,
    *,
    log_rejected: bool = True,
) -> "tuple[list, list]":
    """Filter an iterable of RawSample objects.

    Applies all hard checks from evaluate_sample, plus a batch-level soft
    check for HTML duplicate ratio.

    Parameters
    ----------
    samples:
        Any iterable of RawSample objects.
    config:
        Quality thresholds.  Uses FilterConfig defaults when omitted.
    log_rejected:
        Emit a DEBUG log line for each rejected sample.

    Returns
    -------
    tuple[list, list]
        (kept, rejected) — two separate lists for downstream tracking.
    """
    if config is None:
        config = FilterConfig()

    kept: list = []
    rejected: list = []
    html_seen: dict = {}

    sample_list = list(samples)
    total = len(sample_list)

    for sample in sample_list:
        result = evaluate_sample(sample, config)

        # Batch soft-check: HTML duplicate ratio.
        html_key = (sample.html or "")[:256]
        if html_key:
            html_seen[html_key] = html_seen.get(html_key, 0) + 1
            dup_ratio = html_seen[html_key] / max(total, 1)
            if dup_ratio > config.max_html_duplicate_ratio:
                warning = f"html_dup_ratio_{dup_ratio:.2f}>{config.max_html_duplicate_ratio}"
                result.warnings.append(warning)
                if config.strict:
                    result.hard_failures.append(warning)
                    result.passed = False

        if result.passed:
            kept.append(sample)
        else:
            rejected.append(sample)
            if log_rejected:
                log.debug(
                    "Rejected %s: %s",
                    result.sample_id,
                    "; ".join(result.hard_failures),
                )

    log.info(
        "Quality filter: %d total -> %d kept, %d rejected (%.1f%% pass rate)",
        total,
        len(kept),
        len(rejected),
        100 * len(kept) / max(total, 1),
    )
    return kept, rejected


# ---------------------------------------------------------------------------
# Convenience: filter + summarise
# ---------------------------------------------------------------------------


def filter_and_report(
    samples: Sequence,
    config: "FilterConfig | None" = None,
) -> dict:
    """Filter samples and return a summary dict suitable for logging or JSON.

    Returns
    -------
    dict with keys: total, kept, rejected, pass_rate, rejection_reasons, config.
    """
    if config is None:
        config = FilterConfig()

    kept, rejected_list = filter_samples(samples, config=config, log_rejected=False)
    reason_counts: dict = {}
    for sample in rejected_list:
        result = evaluate_sample(sample, config)
        for reason in result.hard_failures:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    total = len(samples)
    return {
        "total": total,
        "kept": len(kept),
        "rejected": len(rejected_list),
        "pass_rate": round(len(kept) / max(total, 1), 4),
        "rejection_reasons": reason_counts,
        "config": {
            "min_image_width": config.min_image_width,
            "min_image_height": config.min_image_height,
            "min_html_bytes": config.min_html_bytes,
            "max_aspect_ratio": config.max_aspect_ratio,
            "require_bboxes": config.require_bboxes,
            "strict": config.strict,
        },
    }
