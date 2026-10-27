# Changelog

## 0.1.0 — unreleased (Milestone 1)

* Design IR (schema 1.0.0) with validation, serialization, migrations.
* Classical vision pipeline (illumination flattening, threshold variants, shape/line/text detection,
  rule-based classification with ambiguity flags, containment hierarchy) + synthetic sketch generator.
* IR builder with shared alignment/spacing/repeated-group rules; SVG / HTML / CSS / PNG renderers.
* Undoable editor commands; evaluator with 10 issue codes and sketch-fidelity metrics.
* Repair engine: diagnosis, candidate patches, trial + regression check + exact rollback, fault injection.
* Orchestration (budgets, stopping rules, cancel), Qt-free controller, background tasks, project store.
* PySide6 workbench and `python -m sketchforge demo|gui|info`.
* 174 tests; benchmarks in `experiments/results/`.
