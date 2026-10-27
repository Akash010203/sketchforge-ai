"""Generation validation: static checks on generated source text before writing to disk."""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ValidationIssue:
    file_path: str
    line: int
    message: str
    severity: str = "error"   # "error" | "warning"


@dataclass
class ValidationResult:
    issues: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def __repr__(self) -> str:
        if self.ok:
            return "ValidationResult(ok)"
        return f"ValidationResult(errors={len(self.errors)}, warnings={len(self.issues) - len(self.errors)})"


def validate_text(path: str, content: str) -> ValidationResult:
    """Dispatch static validation by file extension."""
    ext = Path(path).suffix.lower()
    if ext == ".py":
        return _validate_python(path, content)
    if ext == ".json":
        return _validate_json(path, content)
    if ext in (".ts", ".tsx"):
        return _validate_typescript_basic(path, content)
    if ext == ".css":
        return _validate_css_basic(path, content)
    return ValidationResult(issues=[])


def validate_bundle(files: dict[str, str]) -> dict[str, ValidationResult]:
    """Validate all files in a generated project.  Returns per-path results."""
    return {path: validate_text(path, content) for path, content in files.items()}


# ---------------------------------------------------------------------------
# Per-language validators
# ---------------------------------------------------------------------------

def _validate_python(path: str, content: str) -> ValidationResult:
    issues: list[ValidationIssue] = []
    try:
        ast.parse(content, filename=path)
    except SyntaxError as e:
        issues.append(ValidationIssue(path, e.lineno or 0, f"SyntaxError: {e.msg}"))
    # Detect common patterns that indicate placeholder/stub code
    for i, line in enumerate(content.splitlines(), 1):
        if "raise NotImplementedError" in line:
            issues.append(ValidationIssue(path, i, "Unimplemented stub (NotImplementedError)", "warning"))
        if "TODO" in line or "FIXME" in line:
            issues.append(ValidationIssue(path, i, "TODO/FIXME found", "warning"))
    return ValidationResult(issues=issues)


def _validate_json(path: str, content: str) -> ValidationResult:
    issues: list[ValidationIssue] = []
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        issues.append(ValidationIssue(path, e.lineno, f"JSONDecodeError: {e.msg}"))
    return ValidationResult(issues=issues)


def _validate_typescript_basic(path: str, content: str) -> ValidationResult:
    """Heuristic TypeScript checks (no tsc invocation — that happens in verification)."""
    issues: list[ValidationIssue] = []
    lines = content.splitlines()
    open_braces = content.count("{") - content.count("}")
    open_parens = content.count("(") - content.count(")")
    if open_braces != 0:
        issues.append(ValidationIssue(path, len(lines), f"Unbalanced braces: {open_braces:+d}", "warning"))
    if open_parens != 0:
        issues.append(ValidationIssue(path, len(lines), f"Unbalanced parentheses: {open_parens:+d}", "warning"))
    # Check for unclosed JSX tags (very basic)
    for i, line in enumerate(lines, 1):
        if re.search(r"<[A-Z][A-Za-z]+ ", line) and "/>" not in line and not re.search(r"</[A-Z]", content):
            # Not conclusive but flag for review
            pass
    return ValidationResult(issues=issues)


def _validate_css_basic(path: str, content: str) -> ValidationResult:
    issues: list[ValidationIssue] = []
    open_braces = content.count("{") - content.count("}")
    if open_braces != 0:
        issues.append(ValidationIssue(path, 0, f"Unbalanced CSS braces: {open_braces:+d}"))
    return ValidationResult(issues=issues)
