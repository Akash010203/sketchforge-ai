"""Central dataset catalogue.

Provides a single point of truth for every dataset the pipeline knows about:
the manifest-declared external sources plus the locally-generated synthetic set.

The registry:
  * Loads and validates the project manifest from ``datasets/manifests/``.
  * Exposes convenience queries — what is available locally, what is eligible
    for training, what needs pilot download.
  * Never downloads anything itself: callers that need data use
    ``source_adapters.download_pilot()``.

Usage::

    from sketchforge.datasets.registry import DatasetRegistry
    reg = DatasetRegistry.load()
    for entry in reg.training_eligible():
        print(entry.id, entry.license_spdx)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sketchforge.datasets.license_audit import load_manifest
from sketchforge.datasets.manifest_schema import DatasetManifest, DatasetRecord, TRAINING_LICENSES
from sketchforge.utilities.paths import repo_root

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal entry — richer than the raw Pydantic model
# ---------------------------------------------------------------------------


@dataclass
class CatalogueEntry:
    """One dataset in the registry, augmented with local state."""
    record: DatasetRecord
    local_artifacts_present: bool = False
    sample_count: int = 0

    # ---- convenience accessors ----
    @property
    def id(self) -> str:
        return self.record.id

    @property
    def name(self) -> str:
        return self.record.name

    @property
    def license_spdx(self) -> str:
        return self.record.license_spdx

    @property
    def access(self) -> str:
        return self.record.access

    @property
    def training_eligible(self) -> bool:
        return self.record.license_spdx in TRAINING_LICENSES

    @property
    def expected_gib(self) -> float | None:
        b = self.record.expected_download_bytes
        return round(b / (1024 ** 3), 2) if b else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "license_spdx": self.license_spdx,
            "access": self.access,
            "training_eligible": self.training_eligible,
            "local_artifacts_present": self.local_artifacts_present,
            "sample_count": self.sample_count,
            "expected_gib": self.expected_gib,
            "source_url": self.record.source_url,
        }


@dataclass
class SyntheticEntry:
    """Represents the locally-generated synthetic sketch set."""
    data_dir: Path
    sample_count: int = 0

    @property
    def id(self) -> str:
        return "synthetic"

    @property
    def name(self) -> str:
        return "SketchForge synthetic sketches (local)"

    @property
    def training_eligible(self) -> bool:
        return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "training_eligible": True,
            "local_artifacts_present": self.sample_count > 0,
            "sample_count": self.sample_count,
            "data_dir": str(self.data_dir),
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class DatasetRegistry:
    """Catalogue of all known datasets: external (manifest) + local synthetic."""

    def __init__(
        self,
        manifest: DatasetManifest,
        datasets_root: Path,
    ) -> None:
        self._manifest = manifest
        self._root = datasets_root
        self._entries: list[CatalogueEntry] = []
        self._synthetic: SyntheticEntry | None = None
        self._build()

    # ------------------------------------------------------------------ construction
    def _build(self) -> None:
        raw_dir = self._root / "raw"
        processed_dir = self._root / "processed"
        for record in self._manifest.datasets:
            local = raw_dir / record.id
            if not local.is_dir():
                # Check alias without version suffix (e.g., websight-v02 -> websight)
                alt = raw_dir / record.id.split("-v0")[0]
                if alt.is_dir():
                    local = alt
            raw_count = 0
            if local.is_dir():
                try:
                    from sketchforge.datasets.source_adapters import get_adapter
                    adapter = get_adapter(record.id)
                except KeyError:
                    # Keep a file-presence count for non-image/code corpora that
                    # do not currently have a normalized source adapter.
                    raw_count = self._count_samples(local)
                else:
                    # Avoid counting metadata-only caches as usable datasets.
                    if adapter.is_available():
                        raw_count = self._count_samples(local)
            processed_count = self._count_samples(processed_dir / record.id)
            count = max(raw_count, processed_count)
            self._entries.append(CatalogueEntry(
                record=record,
                local_artifacts_present=count > 0,
                sample_count=count,
            ))

        syn_dir = self._root / "synthetic"
        count = self._count_samples(syn_dir)
        self._synthetic = SyntheticEntry(data_dir=syn_dir, sample_count=count)

    @staticmethod
    def _count_samples(path: Path) -> int:
        if not path.is_dir():
            return 0
        # Hugging Face save_to_disk() exports its row count in dataset_info.json.
        dataset_info = path / "dataset_info.json"
        if dataset_info.is_file():
            try:
                info = json.loads(dataset_info.read_text(encoding="utf-8"))
                splits = info.get("splits", {})
                if splits:
                    return sum(int(split.get("num_examples", 0)) for split in splits.values())
            except (OSError, ValueError, TypeError):
                pass
        # 1. Count images recursively (e.g. sketches/, webpages/, images/)
        img_count = sum(1 for f in path.rglob("*") if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
        if img_count > 0:
            return img_count
        # 2. Count parquet samples if parquet files are present
        parquets = list(path.rglob("*.parquet"))
        if parquets:
            try:
                import pyarrow.parquet as pq
                return sum(pq.read_metadata(str(p)).num_rows for p in parquets)
            except Exception:
                return len(parquets)
        # 3. Count jsonl records if present
        jsonls = list(path.rglob("*.jsonl"))
        if jsonls:
            try:
                return sum(sum(1 for _ in open(j, "rb")) for j in jsonls)
            except Exception:
                return len(jsonls)
        # 4. Count zip files or other archives
        zips = list(path.rglob("*.zip"))
        if zips:
            return len(zips)
        return 0

    @staticmethod
    def _count_images(path: Path) -> int:
        return DatasetRegistry._count_samples(path)

    # ------------------------------------------------------------------ factory
    @classmethod
    def load(cls, manifest_path: Path | str | None = None) -> "DatasetRegistry":
        """Load from the project manifest.  Falls back to an empty manifest on error."""
        root = repo_root() / "datasets"
        path = Path(manifest_path) if manifest_path else root / "manifests" / "manifest.json"
        try:
            manifest = load_manifest(path)
        except (ValueError, OSError) as exc:
            log.warning("DatasetRegistry: could not load manifest at %s: %s", path, exc)
            manifest = DatasetManifest(
                schema_version=1,
                reviewed_on="1970-01-01",
                datasets=[],
            )
        return cls(manifest=manifest, datasets_root=root)

    # ------------------------------------------------------------------ queries
    @property
    def entries(self) -> list[CatalogueEntry]:
        return list(self._entries)

    @property
    def synthetic(self) -> SyntheticEntry | None:
        return self._synthetic

    def get(self, dataset_id: str) -> CatalogueEntry | None:
        return next((e for e in self._entries if e.id == dataset_id), None)

    def training_eligible(self) -> list[CatalogueEntry]:
        """Dataset records on the approved training licence allowlist."""
        return [e for e in self._entries if e.training_eligible]

    def locally_available(self) -> list[CatalogueEntry]:
        """Dataset records that have local raw files."""
        return [e for e in self._entries if e.local_artifacts_present]

    def pending_download(self) -> list[CatalogueEntry]:
        """Eligible datasets that have not yet been downloaded."""
        return [e for e in self._entries if e.training_eligible and not e.local_artifacts_present]

    def summary(self) -> dict:
        syn_count = self._synthetic.sample_count if self._synthetic else 0
        return {
            "manifest_datasets": len(self._entries),
            "training_eligible": len(self.training_eligible()),
            "locally_available": len(self.locally_available()),
            "pending_download": len(self.pending_download()),
            "synthetic_samples": syn_count,
        }

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "datasets": [e.to_dict() for e in self._entries],
            "synthetic": self._synthetic.to_dict() if self._synthetic else None,
        }
