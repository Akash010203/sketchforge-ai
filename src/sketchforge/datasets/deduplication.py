"""Image perceptual hashing and URL deduplication.

Prevents duplicate images from entering the training set, which would inflate
metrics and cause data leakage between splits.

Two complementary strategies
-----------------------------
* **URL deduplication** — fast; catches exact-URL duplicates before any
  download, with a persistent ``seen_urls.json`` ledger.
* **Perceptual-hash deduplication** — catches near-duplicates (rescaled,
  lightly compressed, or JPEG-re-encoded copies of the same image) using
  difference-hashing (dHash).  A Hamming-distance threshold controls
  sensitivity.

dHash algorithm
---------------
1. Resize image to (W+1) × H (default 9×8) in grayscale.
2. Compute horizontal pixel differences per row.
3. Pack bits (diff > 0) into a 64-bit integer.

Hamming distance ≤ 5 (out of 64) is treated as a near-duplicate by default.
The threshold is configurable so stricter or looser policies can be applied.

Usage::

    from sketchforge.datasets.deduplication import ImageDeduplicator
    dedup = ImageDeduplicator()
    for sample in adapter.samples():
        if dedup.is_duplicate(sample.image_path):
            continue
        process(sample)
    dedup.save_ledger()
"""
from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)

_DEFAULT_HASH_SIZE = 8   # produces a 64-bit hash (size * size bits)
_DEFAULT_THRESHOLD = 5   # Hamming distance ≤ this is a near-duplicate


# ---------------------------------------------------------------------------
# dHash computation
# ---------------------------------------------------------------------------


def dhash(image: "Any", hash_size: int = _DEFAULT_HASH_SIZE) -> int:
    """Compute a difference hash (dHash) integer for *image*.

    Parameters
    ----------
    image:
        A NumPy uint8 array (H, W) or (H, W, C) — greyscale or BGR/RGB.
    hash_size:
        Side length of the internal thumbnail.  The hash has
        ``hash_size * hash_size`` bits.  8 → 64-bit hash.

    Returns
    -------
    int — a non-negative integer representing the hash.
    """
    import numpy as np
    import cv2  # type: ignore[import]

    arr = np.asarray(image, dtype=np.uint8)
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(arr, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    # horizontal differences
    diff = resized[:, 1:] > resized[:, :-1]
    bits = diff.flatten().tolist()
    # pack into int
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def dhash_from_path(path: Path, hash_size: int = _DEFAULT_HASH_SIZE) -> int | None:
    """Load an image from *path* and return its dHash, or None on IO error."""
    try:
        import cv2
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return dhash(img, hash_size)
    except Exception as exc:  # noqa: BLE001
        log.debug("dhash_from_path failed for %s: %s", path, exc)
        return None


def hamming_distance(a: int, b: int) -> int:
    """Return the Hamming distance between two integer hashes."""
    return bin(a ^ b).count("1")


def hash_to_hex(h: int, n_bits: int = 64) -> str:
    """Convert a hash integer to a fixed-width hex string."""
    n_bytes = (n_bits + 7) // 8
    return h.to_bytes(n_bytes, "big").hex()


def hex_to_hash(s: str) -> int:
    return int(s, 16)


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------


class ImageDeduplicator:
    """Stateful deduplicator for a sequence of image samples.

    Parameters
    ----------
    ledger_path:
        Where the hash ledger is persisted (JSON).  Defaults to
        ``datasets/dedup_ledger.json``.
    threshold:
        Hamming distance at or below which two images are considered
        near-duplicates.
    hash_size:
        dHash resolution (default 8 → 64 bits).
    """

    def __init__(
        self,
        ledger_path: Path | str | None = None,
        threshold: int = _DEFAULT_THRESHOLD,
        hash_size: int = _DEFAULT_HASH_SIZE,
    ) -> None:
        from sketchforge.utilities.paths import repo_root
        self._ledger_path = (
            Path(ledger_path) if ledger_path
            else repo_root() / "datasets" / "dedup_ledger.json"
        )
        self.threshold = threshold
        self.hash_size = hash_size

        # {hex_hash: sample_id} — the canonical first occurrence of each hash
        self._seen: dict[int, str] = {}
        self._seen_urls: set[str] = set()
        self._duplicates: int = 0

        self._load_ledger()

    # ------------------------------------------------------------------ URL dedup
    def is_url_duplicate(self, url: str) -> bool:
        if url in self._seen_urls:
            self._duplicates += 1
            return True
        return False

    def register_url(self, url: str) -> None:
        self._seen_urls.add(url)

    # ------------------------------------------------------------------ perceptual dedup
    def is_duplicate(
        self,
        image_or_path: "Path | Any",
        sample_id: str = "",
    ) -> bool:
        """Return True if *image_or_path* is a near-duplicate of something already seen.

        If not a duplicate, registers the image hash automatically.
        """
        if isinstance(image_or_path, Path):
            h = dhash_from_path(image_or_path, self.hash_size)
        else:
            try:
                h = dhash(image_or_path, self.hash_size)
            except Exception:  # noqa: BLE001
                return False

        if h is None:
            return False

        for seen_hash in self._seen:
            if hamming_distance(h, seen_hash) <= self.threshold:
                self._duplicates += 1
                log.debug(
                    "Near-duplicate: %s matches existing %s (dist %d)",
                    sample_id or str(image_or_path),
                    self._seen[seen_hash],
                    hamming_distance(h, seen_hash),
                )
                return True

        self._seen[h] = sample_id or str(image_or_path)
        return False

    def register_hash(self, h: int, sample_id: str = "") -> None:
        """Manually register a hash without the duplicate check."""
        self._seen[h] = sample_id

    # ------------------------------------------------------------------ batch
    def filter_samples(
        self,
        samples: Sequence,
        *,
        id_attr: str = "sample_id",
        path_attr: str = "image_path",
    ) -> list:
        """Return a new list with duplicate samples removed (in-order, first seen kept)."""
        unique = []
        for s in samples:
            sid = getattr(s, id_attr, "")
            url = getattr(s, "provenance", {}).get("url", "")
            if url and self.is_url_duplicate(url):
                continue
            img_path = getattr(s, path_attr, None)
            if img_path and self.is_duplicate(img_path, sample_id=sid):
                continue
            if url:
                self.register_url(url)
            unique.append(s)
        return unique

    # ------------------------------------------------------------------ I/O
    @property
    def n_registered(self) -> int:
        return len(self._seen)

    @property
    def n_duplicates_found(self) -> int:
        return self._duplicates

    def save_ledger(self) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "threshold": self.threshold,
            "hash_size": self.hash_size,
            "n_registered": self.n_registered,
            "seen_urls": sorted(self._seen_urls),
            "hashes": {
                hash_to_hex(h, self.hash_size ** 2): sid
                for h, sid in self._seen.items()
            },
        }
        self._ledger_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        log.info(
            "Dedup ledger saved: %d hashes, %d URLs → %s",
            self.n_registered, len(self._seen_urls), self._ledger_path,
        )

    def _load_ledger(self) -> None:
        if not self._ledger_path.is_file():
            return
        try:
            data = json.loads(self._ledger_path.read_text(encoding="utf-8"))
            self._seen_urls = set(data.get("seen_urls", []))
            for hex_h, sid in data.get("hashes", {}).items():
                self._seen[hex_to_hash(hex_h)] = sid
            log.debug(
                "Dedup ledger loaded: %d hashes, %d URLs",
                len(self._seen), len(self._seen_urls),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            log.warning("Could not load dedup ledger at %s: %s", self._ledger_path, exc)

    def summary(self) -> dict:
        return {
            "registered": self.n_registered,
            "urls_seen": len(self._seen_urls),
            "duplicates_rejected": self.n_duplicates_found,
            "threshold": self.threshold,
        }


# ---------------------------------------------------------------------------
# Convenience: deduplicate a list of RawSample objects
# ---------------------------------------------------------------------------

def deduplicate_samples(
    samples: Sequence,
    ledger_path: Path | None = None,
    threshold: int = _DEFAULT_THRESHOLD,
) -> list:
    """Deduplicate a sequence of :class:`~source_adapters.RawSample` objects.

    Returns a list of unique samples (first occurrence kept).
    The dedup ledger is saved after filtering.
    """
    dedup = ImageDeduplicator(ledger_path=ledger_path, threshold=threshold)
    unique = dedup.filter_samples(samples)
    dedup.save_ledger()
    log.info(
        "Deduplication: %d → %d samples (%d near-duplicates removed)",
        len(list(samples)), len(unique), dedup.n_duplicates_found,
    )
    return unique
