import numpy as np
import pytest

from sketchforge.integrations.nvidia.local_inference import LocalInferenceSession, _resolve_checkpoint


def test_default_checkpoint_prefers_training_output(tmp_path, monkeypatch):
    from sketchforge.utilities import paths

    checkpoint = tmp_path / "checkpoints" / "component_detector_v1" / "best.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.touch()
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)

    assert _resolve_checkpoint(None) == checkpoint


def test_local_session_loads_checkpoint_and_decodes_model_outputs(tmp_path):
    torch = pytest.importorskip("torch")
    from sketchforge.models.component_detector.architecture import build_model

    checkpoint = tmp_path / "detector.pt"
    model = build_model(num_classes=15)
    torch.save({
        "epoch": 7,
        "config": {"num_classes": 15},
        "model_state_dict": model.state_dict(),
    }, checkpoint)

    session = LocalInferenceSession(checkpoint_path=checkpoint, device="cpu")
    result = session.predict(np.full((128, 128), 255, dtype=np.uint8))

    assert result.ok
    assert result.device == "cpu"
    assert result.checkpoint_epoch == 7
