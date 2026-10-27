"""Unit tests for generated-project inspection and verification reports/runners."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sketchforge.verification import project_inspector
from sketchforge.verification.build_runner import run_build
from sketchforge.verification.lint_runner import run_lint, run_typecheck
from sketchforge.verification.project_inspector import inspect_project
from sketchforge.verification.test_runner import run_tests
from sketchforge.verification.verification_report import VerificationReport, VerificationStep


def test_inspect_react_typescript_project_reports_required_files(tmp_path):
    for rel in project_inspector.REQUIRED_REACT_TS:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules" / "dependency").mkdir(parents=True)
    (tmp_path / "node_modules" / "dependency" / "index.js").write_text("", encoding="utf-8")

    result = inspect_project(tmp_path)

    assert result["ok"]
    assert result["stack"] == "react-ts"
    assert result["required_missing"] == []
    assert result["total_files"] == len(project_inspector.REQUIRED_REACT_TS)


def test_inspect_html_project_reports_missing_and_present_files(tmp_path):
    (tmp_path / "README.md").write_text("generated", encoding="utf-8")

    result = inspect_project(tmp_path)

    assert not result["ok"]
    assert result["stack"] == "html-css-js"
    assert result["required_present"] == ["README.md"]
    assert result["required_missing"] == ["css/style.css"]


def test_report_aggregates_steps_and_serializes_bounded_output(tmp_path):
    report = VerificationReport(project_root=str(tmp_path))
    report.add(VerificationStep("lint", True, duration_ms=2.345, stdout="ok"))
    report.add(
        VerificationStep("build", False, stderr="\n".join(f"error {i}" for i in range(8)), returncode=1)
    )

    result = report.to_dict()
    summary = report.summary()

    assert not report.ok
    assert (report.passed, report.failed) == (1, 1)
    assert result["steps"][0]["duration_ms"] == 2.3
    assert len(result["steps"][1]["stderr"]) == 63
    assert "FAIL (1/2 steps)" in summary
    assert "build" in summary and "error 5" not in summary

    output = tmp_path / "report.json"
    report.save(output)
    assert '"failed": 1' in output.read_text(encoding="utf-8")


def test_build_lint_typecheck_and_test_runners_forward_commands(tmp_path, monkeypatch):
    calls: list[tuple[list[str], Path, float]] = []

    class FakeSession:
        def run(self, command, *, cwd, timeout):
            calls.append((command, cwd, timeout))
            return SimpleNamespace(ok=True, stdout="passed", stderr="", returncode=0)

    session = FakeSession()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sketchforge.verification.test_runner._run_vitest",
        lambda s, p: VerificationStep("vitest", True),
    )

    assert run_build(session, tmp_path).ok
    assert run_lint(session, tmp_path).name == "eslint"
    assert run_typecheck(session, tmp_path).name == "tsc --noEmit"
    assert run_tests(session, tmp_path).name == "vitest"
    assert [call[0] for call in calls] == [
        ["npm", "run", "build"],
        ["npx", "eslint", "src", "--ext", ".ts,.tsx", "--max-warnings", "10"],
        ["npx", "tsc", "--noEmit"],
    ]


def test_python_test_runner_selection_and_no_tests_fallback(tmp_path, monkeypatch):
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    called = []
    monkeypatch.setattr(
        "sketchforge.verification.test_runner._run_pytest",
        lambda s, p: called.append(p) or VerificationStep("pytest", True),
    )
    assert run_tests(object(), tmp_path).name == "pytest"
    assert called == [tmp_path]

    empty = run_tests(object(), tmp_path / "empty")
    assert empty.ok
    assert "No test runner found" in empty.notes

