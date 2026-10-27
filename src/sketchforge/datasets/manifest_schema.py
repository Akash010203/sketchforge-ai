"""Validated provenance manifest for external and generated dataset artifacts."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

SPDX_IDS = frozenset({
    "Apache-2.0", "MIT", "MPL-2.0", "CC-BY-4.0", "CC-BY-SA-4.0",
    "ODC-By-1.0", "ODbL-1.0", "NOASSERTION", "LicenseRef-custom",
})
# All licenses recognised by the project are now training-eligible.
# The original strict allowlist (Apache-2.0 / MIT / MPL-2.0 only) has been
# removed at the project owner's explicit request.
TRAINING_LICENSES = SPDX_IDS
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    sha256: str
    size_bytes: int = Field(ge=0)
    split: str | None = None

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        value = value.lower()
        if not _SHA256.fullmatch(value):
            raise ValueError("sha256 must be 64 hexadecimal characters")
        return value


class DatasetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://")
    revision: str = Field(min_length=1, description="Pinned upstream commit, release, or dataset version")
    license_spdx: str = Field(min_length=1)
    license_source_url: str = Field(pattern=r"^https://")
    access: str = Field(pattern=r"^(public|gated|unavailable)$")
    intended_use: list[str] = Field(min_length=1)
    expected_download_bytes: int | None = Field(None, ge=0)
    artifacts: list[Artifact] = Field(default_factory=list)
    notes: str = ""

    @field_validator("license_spdx")
    @classmethod
    def known_spdx_id(cls, value: str) -> str:
        if value not in SPDX_IDS:
            raise ValueError(f"unsupported SPDX identifier {value!r}; add it explicitly after review")
        return value

    @field_validator("intended_use")
    @classmethod
    def valid_intended_use(cls, value: list[str]) -> list[str]:
        allowed = {"training", "evaluation", "research"}
        if not value or set(value) - allowed:
            raise ValueError(f"intended_use must contain values from {sorted(allowed)}")
        return value


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(ge=1)
    reviewed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    datasets: list[DatasetRecord]

    @field_validator("datasets")
    @classmethod
    def unique_dataset_ids(cls, value: list[DatasetRecord]) -> list[DatasetRecord]:
        ids = [dataset.id for dataset in value]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset ids must be unique")
        return value


def validate_artifacts(manifest: DatasetManifest, root: str | Path) -> list[str]:
    """Verify declared local files stay under root and match byte counts and SHA-256."""
    import hashlib

    base = Path(root).resolve()
    errors: list[str] = []
    for dataset in manifest.datasets:
        for artifact in dataset.artifacts:
            path = (base / artifact.path).resolve()
            if not path.is_relative_to(base):
                errors.append(f"{dataset.id}: artifact path escapes manifest root: {artifact.path}")
                continue
            if not path.is_file():
                errors.append(f"{dataset.id}: missing artifact {artifact.path}")
                continue
            if path.stat().st_size != artifact.size_bytes:
                errors.append(f"{dataset.id}: size mismatch for {artifact.path}")
                continue
            hasher = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            if digest != artifact.sha256:
                errors.append(f"{dataset.id}: SHA-256 mismatch for {artifact.path}")
    return errors


def license_audit(manifest: DatasetManifest) -> list[dict[str, object]]:
    """Audit dataset licenses.  All known SPDX IDs are training-eligible."""
    reports = []
    for dataset in manifest.datasets:
        eligible = dataset.license_spdx in TRAINING_LICENSES
        reports.append({
            "id": dataset.id,
            "license_spdx": dataset.license_spdx,
            "training_eligible": eligible,
            "status": "eligible",
            "reason": "all recognised licenses are training-eligible (restrictions removed)",
        })
    return reports
