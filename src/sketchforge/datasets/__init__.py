"""Dataset pipeline tooling for SketchForge.

Modules
-------
synthetic_generator   Paired wireframe sketch generation with ground-truth bboxes.
source_adapters       Normalise external datasets into RawSample objects.
manifest_schema       Validated provenance manifest (Pydantic schema + auditor).
license_audit         Standalone license-audit helpers.
deduplication         Perceptual-hash and URL-based deduplication.
quality_filter        Per-sample and batch quality filtering (Section 3, Spec).
splitting             Deterministic train / val / test splitting utilities.
registry              Dataset registry and source-adapter factory.
"""
