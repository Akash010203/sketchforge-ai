# Checkpoints

Model checkpoints are generated artifacts and are not committed. The NVIDIA local runtime loads
SketchForge's component detector from `component_detector_v1/best.pt` by default (or the legacy
`component_detector.pt` path). If neither exists, create a checkpoint with
`python scripts/train_component_detector.py`.

These checkpoints are **not Nemotron weights**. The local runtime does not load Nemotron GGUF/AWQ
models. A local detector checkpoint can load successfully while still having poor accuracy; check
its training report before relying on its predictions. Nebius-served Nemotron is a separate remote
provider path.
