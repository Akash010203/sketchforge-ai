"""Train / validation / test dataset splitting.

Provides deterministic, reproducible splits of any sequence of
:class:`~source_adapters.RawSample` objects.  All split functions are
**stateless pure functions** so they can be composed freely and tested in
isolation.

Two split strategies are supported:

random_split
    Shuffle a flat list of samples with a fixed seed, then carve out
    train / val / test slices according to the given ratios.  Fast and
    suitable when all samples are drawn from the same distribution.

stratified_split
    Partition samples first by ``source_dataset`` (or any string key), then
    draw the required fraction from each stratum independently.  Use when the
    dataset mix is heterogeneous and you want each split to mirror the
    overall source distribution.

Both strategies guarantee:

* The union of all three splits equals the full input set (no sample is lost).
* Splits are disjoint (no sample appears in more than one split).
* Reproducibility: the same seed always produces the same split.

Usage::

    from sketchforge.datasets.splitting import random_split, stratified_split, SplitRatios

    ratios = SplitRatios(train=0.8, val=0.1, test=0.1)
    train, val, test = random_split(samples, ratios=ratios, seed=42)

    # Preserve per-source balance:
    train, val, test = stratified_split(samples, ratios=ratios, seed=42)
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Sequence

log = logging.getLogger(__name__)

_DEFAULT_TRAIN = 0.8
_DEFAULT_VAL = 0.1
_DEFAULT_TEST = 0.1


# ---------------------------------------------------------------------------
# SplitRatios
# ---------------------------------------------------------------------------


@dataclass
class SplitRatios:
    """Train / val / test fractions.  Must sum to 1.0 (within floating-point tolerance).

    Parameters
    ----------
    train:
        Fraction of samples assigned to the training set.
    val:
        Fraction of samples assigned to the validation set.
    test:
        Fraction of samples assigned to the test set.
    """

    train: float = _DEFAULT_TRAIN
    val: float = _DEFAULT_VAL
    test: float = _DEFAULT_TEST

    def __post_init__(self) -> None:
        total = self.train + self.val + self.test
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"SplitRatios must sum to 1.0, got {total:.6f} "
                f"(train={self.train}, val={self.val}, test={self.test})"
            )
        for name, val in (("train", self.train), ("val", self.val), ("test", self.test)):
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"SplitRatios.{name} must be in [0, 1], got {val}")


# ---------------------------------------------------------------------------
# SplitResult
# ---------------------------------------------------------------------------


@dataclass
class SplitResult:
    """Container for the three output splits.

    Attributes
    ----------
    train:
        Samples designated for model training.
    val:
        Samples designated for validation / early stopping.
    test:
        Samples designated for final evaluation.
    ratios:
        The SplitRatios used to produce this result.
    seed:
        The RNG seed used for reproducibility.
    """

    train: list
    val: list
    test: list
    ratios: SplitRatios
    seed: int

    @property
    def summary(self) -> dict:
        total = len(self.train) + len(self.val) + len(self.test)
        return {
            "total": total,
            "train": len(self.train),
            "val": len(self.val),
            "test": len(self.test),
            "actual_train_ratio": len(self.train) / max(total, 1),
            "actual_val_ratio": len(self.val) / max(total, 1),
            "actual_test_ratio": len(self.test) / max(total, 1),
            "seed": self.seed,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slice_by_ratio(items: list, ratios: SplitRatios) -> "tuple[list, list, list]":
    """Split a *pre-shuffled* list into three contiguous slices."""
    n = len(items)
    n_train = round(n * ratios.train)
    n_val = round(n * ratios.val)
    # Give any rounding remainder to the test set.
    train = items[:n_train]
    val = items[n_train : n_train + n_val]
    test = items[n_train + n_val :]
    return train, val, test


# ---------------------------------------------------------------------------
# random_split
# ---------------------------------------------------------------------------


def random_split(
    samples: Sequence,
    ratios: "SplitRatios | None" = None,
    *,
    seed: int = 42,
) -> "tuple[list, list, list]":
    """Randomly shuffle and split *samples* into train / val / test.

    Parameters
    ----------
    samples:
        A sequence of RawSample objects (or any objects).
    ratios:
        Desired split fractions.  Uses SplitRatios defaults (80/10/10) when
        omitted.
    seed:
        Integer seed for the random number generator.

    Returns
    -------
    tuple[list, list, list]
        (train_samples, val_samples, test_samples)
    """
    if ratios is None:
        ratios = SplitRatios()

    shuffled = list(samples)
    rng = random.Random(seed)
    rng.shuffle(shuffled)

    train, val, test = _slice_by_ratio(shuffled, ratios)

    log.info(
        "random_split (seed=%d): %d -> train=%d / val=%d / test=%d",
        seed, len(samples), len(train), len(val), len(test),
    )
    return train, val, test


# ---------------------------------------------------------------------------
# stratified_split
# ---------------------------------------------------------------------------


def stratified_split(
    samples: Sequence,
    ratios: "SplitRatios | None" = None,
    *,
    seed: int = 42,
    key_attr: str = "source_dataset",
) -> "tuple[list, list, list]":
    """Split *samples* while preserving the distribution of *key_attr*.

    Samples are first grouped by ``sample.{key_attr}``, then each group is
    independently shuffled and split according to *ratios*.  The group
    contributions are concatenated to form the final train / val / test sets.

    Parameters
    ----------
    samples:
        A sequence of RawSample objects (or any objects with *key_attr*).
    ratios:
        Desired split fractions.  Uses SplitRatios defaults (80/10/10) when
        omitted.
    seed:
        Integer seed for the random number generator.
    key_attr:
        Attribute name to stratify by.  Defaults to ``"source_dataset"``.

    Returns
    -------
    tuple[list, list, list]
        (train_samples, val_samples, test_samples)
    """
    if ratios is None:
        ratios = SplitRatios()

    # Group samples by stratum.
    strata: dict = {}
    for sample in samples:
        key = getattr(sample, key_attr, "unknown")
        strata.setdefault(key, []).append(sample)

    all_train: list = []
    all_val: list = []
    all_test: list = []

    rng = random.Random(seed)
    for stratum_key in sorted(strata.keys()):
        group = strata[stratum_key]
        rng.shuffle(group)
        tr, va, te = _slice_by_ratio(group, ratios)
        all_train.extend(tr)
        all_val.extend(va)
        all_test.extend(te)
        log.debug(
            "stratified_split [%s]: %d -> train=%d / val=%d / test=%d",
            stratum_key, len(group), len(tr), len(va), len(te),
        )

    # Shuffle within each split so strata are interleaved.
    rng2 = random.Random(seed + 1)
    rng2.shuffle(all_train)
    rng2.shuffle(all_val)
    rng2.shuffle(all_test)

    log.info(
        "stratified_split (seed=%d, strata=%d): %d -> train=%d / val=%d / test=%d",
        seed, len(strata), len(samples), len(all_train), len(all_val), len(all_test),
    )
    return all_train, all_val, all_test


# ---------------------------------------------------------------------------
# split_and_report
# ---------------------------------------------------------------------------


def split_and_report(
    samples: Sequence,
    ratios: "SplitRatios | None" = None,
    *,
    strategy: str = "random",
    seed: int = 42,
    key_attr: str = "source_dataset",
) -> dict:
    """Split samples and return a summary dict.

    Parameters
    ----------
    strategy:
        ``"random"`` or ``"stratified"``.

    Returns
    -------
    dict with keys: train, val, test, summary.
    """
    if ratios is None:
        ratios = SplitRatios()

    if strategy == "stratified":
        train, val, test = stratified_split(samples, ratios=ratios, seed=seed, key_attr=key_attr)
    else:
        train, val, test = random_split(samples, ratios=ratios, seed=seed)

    total = len(samples)
    return {
        "train": train,
        "val": val,
        "test": test,
        "summary": {
            "total": total,
            "train": len(train),
            "val": len(val),
            "test": len(test),
            "actual_train_ratio": round(len(train) / max(total, 1), 4),
            "actual_val_ratio": round(len(val) / max(total, 1), 4),
            "actual_test_ratio": round(len(test) / max(total, 1), 4),
            "strategy": strategy,
            "seed": seed,
        },
    }
