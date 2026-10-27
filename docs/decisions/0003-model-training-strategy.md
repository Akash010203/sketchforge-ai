# ADR 0003 — Heuristics first; train small models from scratch only against a measured baseline

**Status:** accepted (Phase 6 not started) · **Date:** 2026-10-17

**Decision.** Milestone 1 uses deterministic OpenCV heuristics with explicit, testable rules and
recorded confidence/ambiguity. A learned component detector is added in Phase 6 **only** as a
compact model initialised randomly (no pretrained weights, so the "trained from scratch" claim is
true), trained with fixed seeds and a train/validation/test split by source layout/template to avoid
leakage, and compared with the heuristic baseline on held-out real *and* synthetic sets reported
separately.

**Constraints that shape it.** Local machine: 12 CPU cores, NVIDIA GeForce RTX 4050 Laptop GPU (6 GB VRAM), PyTorch 2.6.0+cu124 with CUDA 12.4 enabled, ~443.9 GB free disk space. Strategy: compact MobileNet-style convolutional detector, bounded batch sizes, CUDA acceleration with CPU fallback, checkpoints + resume, early stopping on validation, and a smoke test (batch loads → forward → finite loss → backward → checkpoint round-trip → valid inference) before any full training run. No claim of success from training loss alone.

**Third-party models** (e.g. the NVIDIA/Nebius integration) are separate, isolated, labelled as not
trained by us, and never counted as "from scratch".

**Exit rule.** If the learned detector does not beat the heuristics on the held-out set, the
heuristics stay the default and the result is documented as such.
