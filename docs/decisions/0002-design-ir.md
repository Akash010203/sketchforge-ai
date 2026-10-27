# ADR 0002 — One Design IR as the contract between all modules

**Status:** accepted · **Date:** 2026-10-17

**Decision.** A single pydantic-v2 document (`design_ir/schema.py`, schema 1.0.0): flat component list
with `parent_id`, **absolute page coordinates in design pixels**, typography/style/layout/interaction,
per-component detection provenance (`source_bbox`, confidence, type scores, evidence, ambiguity), and a
`text_is_inferred` flag. Strict models (`extra="forbid"`, validate on assignment), immutable `BBox`
(3-decimal rounding), deterministic JSON, versioned with migrations.

**Why absolute coordinates.** Alignment, overlap and containment checks are then plain box
comparisons; the HTML exporter converts to parent-relative CSS. Moving a parent moves its subtree
explicitly.

**Why flat list + ids.** Cheap to diff, snapshot and hash (rollback and undo compare hashes);
stable ids let issues keep identity across re-evaluations.

**Why provenance in the IR.** Fidelity metrics and honesty flags (inferred text, ambiguous types)
must survive edits and reloads.

**Consequences.** Every module reads and writes the same structure; every change is a validated
command. Cost: the tree is derived from `parent_id` (indexed lazily), so structural edits must call
`invalidate_index` (done by the helpers in `design_ir/document.py`).
