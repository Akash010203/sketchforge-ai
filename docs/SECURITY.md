# Security

## Threat model (current: Milestone 1)

SketchForge is a local desktop tool that reads image files the user chooses and writes files into
folders the user chooses. The relevant risks are hostile or corrupt input files, accidental data
exposure, and (later) running generated code.

## Controls in place

| Risk | Control | Where / test |
|---|---|---|
| Hostile or oversized image (decompression bomb, wrong type) | extension allow-list, 25 MiB file cap, magic-byte sniff, header-only dimension and pixel-budget check **before** decoding, 64 px minimum side | `vision/image_loader.py`, `tests/unit/test_vision.py` |
| A file renamed to look like an image | content must match a known image signature | `test_extension_must_match_content` |
| Network exposure | the application has no server, opens no ports and makes no requests; the demo summary records `"network": "none…"` | `orchestration/sketch_workflow.py`, `test_demo_final_design_matches_report_hash_and_is_valid` |
| Corrupt/partial writes | atomic writes (temp file + rename) for projects, reports and exports | `utilities/paths.py` |
| Untrusted project files | JSON is parsed by pydantic with `extra="forbid"`, versioned and validated; newer schema versions are rejected | `design_ir/serialization.py`, `migrations.py` |
| Malicious text in designs rendered to HTML/SVG | text and attributes are escaped by the renderers | `rendering/` (tests in `test_renderer.py`) |
| Secrets in the repo | none are used; `.env*` (except `.env.example`) and key files are git-ignored | `.gitignore` |
| Silent data egress | no code path sends user content anywhere. Any future remote provider must be explicitly configured, off by default and documented (below) | — |

## Not yet applicable, but required before they ship

* **Generated-application execution (Phases 8–10)**: must run in a restricted environment (no
  unrestricted host access): command allow-list, resource limits, a scratch directory, a scrubbed
  environment, no network unless the test needs it. Generated code will never run inside the
  SketchForge process.
* **Remote provider (Phase 4)**: when added, the integration sits under `integrations/` only, reads
  credentials from the environment (never from files in the repo), shows the user exactly what will
  be sent before the first request, and keeps working locally if the provider is unreachable.
  `docs/NEBIUS_NVIDIA_INTEGRATION.md` will record exactly when user content leaves the machine.
* **Dependencies**: pin and audit before packaging (Phase 11).

## Reporting

Open a private issue with a reproduction file. Do not include real personal data in sketches.
