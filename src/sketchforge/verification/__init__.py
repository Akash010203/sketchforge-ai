"""Verification package: inspects, lints, builds, tests, and visually verifies generated projects."""
from sketchforge.verification.verification_report import VerificationReport, VerificationStep
from sketchforge.verification.project_inspector import inspect_project
from sketchforge.verification.lint_runner import run_lint
from sketchforge.verification.build_runner import run_build
from sketchforge.verification.test_runner import run_tests

__all__ = [
    "VerificationReport", "VerificationStep",
    "inspect_project", "run_lint", "run_build", "run_tests",
]
