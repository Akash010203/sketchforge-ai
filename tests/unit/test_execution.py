"""Unit tests for command policy, sandbox execution, and cleanup."""

from __future__ import annotations

import pytest

from sketchforge.execution.cleanup import cleanup_sandbox
from sketchforge.execution.command_policy import CommandNotPermitted, assert_permitted, is_permitted
from sketchforge.execution.sandbox import RunResult, _safe_env, open_sandbox


@pytest.mark.parametrize(
    "command",
    [
        ["npm", "install"],
        ["python", "-m", "pytest", "tests"],
        ["npx", "playwright", "test"],
        ["node.exe", "script.js"],
    ],
)
def test_command_policy_allows_supported_tools(command):
    assert is_permitted(command)
    assert_permitted(command)


@pytest.mark.parametrize(
    "command",
    [
        [],
        ["curl", "https://example.com"],
        ["powershell", "-Command", "whoami"],
        ["npm", "publish"],
        ["node", "-e", "process.exit(0)"],
        ["npx", "exec", "some-package"],
    ],
)
def test_command_policy_rejects_unsupported_or_blocked_commands(command):
    assert not is_permitted(command)
    with pytest.raises(CommandNotPermitted):
        assert_permitted(command)


def test_sandbox_runs_allowlisted_process_and_reports_exit_status(tmp_path):
    session = open_sandbox(tmp_path, env={"SF_TEST_VALUE": "passed"})
    try:
        script = session.root / "check_env.py"
        script.write_text(
            "import os\nprint(os.environ['SF_TEST_VALUE'])\n",
            encoding="utf-8",
        )
        result = session.run(["python", str(script)], timeout=10)
        assert isinstance(result, RunResult)
        assert result.ok
        assert result.returncode == 0
        assert result.stdout.strip() == "passed"
        assert not result.timed_out
    finally:
        session.cleanup()
    assert not session.root.exists()


def test_sandbox_rejects_command_before_process_launch(tmp_path):
    session = open_sandbox(tmp_path)
    try:
        with pytest.raises(CommandNotPermitted):
            session.run(["curl", "https://example.com"])
    finally:
        session.cleanup()


def test_safe_environment_strips_secret_variables_and_applies_explicit_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "host-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("PATH", "tool-path")

    env = _safe_env({"SF_TEST_VALUE": "present", "OPENAI_API_KEY": "explicit"})

    assert env["PATH"] == "tool-path"
    assert "AWS_SECRET_ACCESS_KEY" not in env
    # Explicit session overrides are applied after host environment filtering.
    assert env["OPENAI_API_KEY"] == "explicit"
    assert env["SF_TEST_VALUE"] == "present"


def test_cleanup_sandbox_removes_tree_and_is_idempotent(tmp_path):
    sandbox = tmp_path / "sandbox"
    nested = sandbox / "nested" / "file.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("temporary", encoding="utf-8")

    assert cleanup_sandbox(sandbox)
    assert not sandbox.exists()
    assert cleanup_sandbox(sandbox)


def test_run_result_success_requires_zero_return_code_and_no_timeout():
    assert RunResult(["python"], 0, "", "", 1).ok
    assert not RunResult(["python"], 2, "", "failed", 1).ok
    assert not RunResult(["python"], 0, "", "", 1, timed_out=True).ok

