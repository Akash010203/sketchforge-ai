# Dataset Audit

Reviewed: 2026-10-22

This is a provenance and policy screen, not legal advice. The training allowlist is Apache-2.0, MIT, and MPL-2.0.
A code repository license does not establish the license for its dataset. Unknown or inherited data terms stay blocked.

Current filesystem free space: 368.48 GiB; conservative planning budget (50%): 184.24 GiB.

| Candidate | Dataset license | Access | Size estimate | Training | Decision |
|---|---|---|---:|---|---|
| [SALT-NLP Sketch2Code](https://huggingface.co/datasets/SALT-NLP/Sketch2Code) | `ODC-By-1.0` | public | unknown | eligible | eligible_for_pilot_review |
| [HuggingFaceM4 WebSight v0.2](https://huggingface.co/datasets/HuggingFaceM4/WebSight) | `CC-BY-4.0` | public | 20.00 GiB | eligible | eligible_for_pilot_review |
| [WebCode2M](https://huggingface.co/datasets/xcodemind/webcode2m) | `CC-BY-4.0` | public | 20.00 GiB | eligible | eligible_for_pilot_review |
| [Teklia IAM-line Handwriting](https://huggingface.co/datasets/Teklia/IAM-line) | `LicenseRef-custom` | public | 0.26 GiB | eligible | eligible_for_pilot_review |
| [Sketch2Diagram Benchmark](https://huggingface.co/datasets/DiagramAgent/Sketch2Diagram-Benchmark) | `Apache-2.0` | public | 0.13 GiB | eligible | eligible_for_pilot_review |
| [ImageCLEF DrawnUI 2020](https://www.aicrowd.com/challenges/imageclef-2020-drawnui) | `NOASSERTION` | public | unknown | eligible | eligible_for_pilot_review |
| [ImageCLEFdrawnUI 2021 wireframe task](https://www.imageclef.org/2021/drawnui) | `NOASSERTION` | public | unknown | eligible | eligible_for_pilot_review |
| [BigCode CommitPackFT](https://huggingface.co/datasets/bigcode/commitpackft) | `Apache-2.0` | public | 0.31 GiB | eligible | eligible_for_pilot_review |
| [BigCode The Stack Dedup (20 GB sample)](https://huggingface.co/datasets/bigcode/the-stack-dedup) | `LicenseRef-custom` | gated | 20.00 GiB | eligible | blocked_pending_rights_or_license_review |

## Findings

- **SALT-NLP Sketch2Code:** its [repository](https://github.com/SALT-NLP/Sketch2Code) says the dataset follows Design2Code's data terms. The [Design2Code dataset card](https://huggingface.co/datasets/SALT-NLP/Design2Code-hf) identifies ODC-By; the [official project README](https://github.com/NoviScl/Design2Code) limits use to research. The dataset is not approved for training under this project's allowlist.
- **WebSight:** its [dataset card](https://huggingface.co/datasets/HuggingFaceM4/WebSight/blob/10d8285c49c88608dcf82f3f76ee58377a3a1216/README.md) states CC-BY-4.0, requires compliance with original source-content licenses, and requires disclosure when releasing a trained model/application. Its listed compressed size is about 29.24 GiB, so it is not a sub-1-GiB pilot candidate as a full download.
- **ImageCLEFdrawnUI 2021:** the [official task page](https://www.imageclef.org/2021/drawnui) describes the hand-drawn wireframe dataset but does not state a reusable dataset license or provide an unconditional download. Access and rights require confirmation.

## Pilot decision

No external pilot files were downloaded. Current candidates lack clear approval under the project's Apache-2.0/MIT/MPL-2.0 training policy, or have source-rights/access conditions that need review. Continue with the repository's synthetic generator until an eligible source and explicit subset are identified.

Source records and pinned metadata are in [`datasets/manifests/manifest.json`](../datasets/manifests/manifest.json). Re-run `python scripts/audit_datasets.py` after updating it.
