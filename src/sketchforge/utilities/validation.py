"""Generic schema and bounds validation helpers.

This module provides *domain-agnostic* validation primitives that can be
reused across SketchForge subsystems without pulling in subsystem-specific
imports.  Domain-specific validators (Design IR, generation output, etc.)
live in their own packages and may call into these helpers.

Sections
--------

**Result types**
    :class:`ValidationSeverity`, :class:`Issue`, :class:`Result`

**Scalar / range checks**
    :func:`check_in_range`, :func:`check_positive`, :func:`check_non_negative`

**String checks**
    :func:`check_non_empty_str`, :func:`check_str_length`, :func:`check_enum_member`

**Collection checks**
    :func:`check_non_empty_seq`, :func:`check_unique`, :func:`check_no_duplicate_keys`

**Mapping / schema checks**
    :func:`check_required_keys`, :func:`check_no_extra_keys`

**Type coercion guards**
    :func:`check_is_type`

**High-level schema validator**
    :class:`SchemaValidator` — accumulate issues via a fluent API and raise at
    the end with :meth:`~SchemaValidator.raise_if_invalid`.

**Convenience assertions** (single-call raise-on-fail wrappers)
    :func:`assert_in_range`, :func:`assert_positive`, :func:`assert_non_negative`,
    :func:`assert_non_empty_str`, :func:`assert_required_keys`
"""

from __future__ import annotations

import enum
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sketchforge.exceptions import DesignValidationError

# ---------------------------------------------------------------------------
# Severity & Issue
# ---------------------------------------------------------------------------


class ValidationSeverity(str, enum.Enum):
    """Ordered severity levels, low → high."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    def __ge__(self, other: object) -> bool:
        if isinstance(other, ValidationSeverity):
            return _SEV_ORDER[self] >= _SEV_ORDER[other]
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, ValidationSeverity):
            return _SEV_ORDER[self] > _SEV_ORDER[other]
        return NotImplemented


_SEV_ORDER: dict[ValidationSeverity, int] = {
    ValidationSeverity.INFO: 0,
    ValidationSeverity.WARNING: 1,
    ValidationSeverity.ERROR: 2,
}


@dataclass(frozen=True)
class Issue:
    """A single validation finding.

    Parameters
    ----------
    code:
        Short machine-readable identifier (e.g. ``"E_OUT_OF_RANGE"``).
    message:
        Human-readable description of the problem.
    field:
        Optional dotted field path identifying what was validated
        (e.g. ``"page.width"``).
    severity:
        :class:`ValidationSeverity` level; defaults to ``ERROR``.
    """

    code: str
    message: str
    field: str | None = None
    severity: ValidationSeverity = ValidationSeverity.ERROR

    def __str__(self) -> str:
        where = f"[{self.field}] " if self.field else ""
        return f"{self.severity.value.upper()} {self.code}: {where}{self.message}"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class Result:
    """Container for all :class:`Issue` objects collected during a validation pass.

    Create one, call ``add()`` / ``extend()`` to accumulate findings, then
    either inspect :attr:`ok` or call :meth:`raise_if_invalid`.
    """

    issues: list[Issue] = field(default_factory=list)

    # -- querying -----------------------------------------------------------

    @property
    def ok(self) -> bool:
        """``True`` iff there are no ERROR-severity issues."""
        return not self.errors

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]

    @property
    def infos(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.INFO]

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    # -- accumulation -------------------------------------------------------

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)

    def extend(self, other: Result) -> None:
        self.issues.extend(other.issues)

    def error(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
    ) -> None:
        """Append an ERROR-level issue (convenience shorthand)."""
        self.add(Issue(code=code, message=message, field=field, severity=ValidationSeverity.ERROR))

    def warning(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
    ) -> None:
        """Append a WARNING-level issue (convenience shorthand)."""
        self.add(Issue(code=code, message=message, field=field, severity=ValidationSeverity.WARNING))

    def info(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
    ) -> None:
        """Append an INFO-level issue (convenience shorthand)."""
        self.add(Issue(code=code, message=message, field=field, severity=ValidationSeverity.INFO))

    # -- conversion ---------------------------------------------------------

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "errors": [str(e) for e in self.errors],
            "warnings": [str(w) for w in self.warnings],
            "infos": [str(i) for i in self.infos],
        }

    def raise_if_invalid(self, exception_class: type[Exception] = DesignValidationError) -> None:
        """Raise *exception_class* listing the first five errors if :attr:`ok` is ``False``.

        Parameters
        ----------
        exception_class:
            The exception type to raise.  Must accept a single string argument.
            Defaults to :class:`~sketchforge.exceptions.DesignValidationError`.
        """
        if self.ok:
            return
        summary = "; ".join(str(e) for e in self.errors[:5])
        extra = f" (+{len(self.errors) - 5} more)" if len(self.errors) > 5 else ""
        raise exception_class(f"Validation failed: {summary}{extra}")

    def __repr__(self) -> str:
        if self.ok:
            return f"Result(ok, warnings={len(self.warnings)})"
        return f"Result(errors={len(self.errors)}, warnings={len(self.warnings)})"


# ---------------------------------------------------------------------------
# Scalar / range checks
# ---------------------------------------------------------------------------

_MISSING = object()


def check_in_range(
    value: Any,
    *,
    lo: float | None = None,
    hi: float | None = None,
    lo_inclusive: bool = True,
    hi_inclusive: bool = True,
    field: str | None = None,
    code: str = "E_OUT_OF_RANGE",
) -> Result:
    """Check that a numeric *value* lies within [*lo*, *hi*] (bounds optional).

    Parameters
    ----------
    value:
        The value to test.  Must support comparison with float.
    lo / hi:
        Optional lower / upper bounds.  ``None`` means "no bound".
    lo_inclusive / hi_inclusive:
        Whether the respective bound is inclusive (default: both inclusive).
    field:
        Dotted field path for the :class:`Issue`.
    code:
        Issue code for out-of-range findings.
    """
    result = Result()
    try:
        v = float(value)
    except (TypeError, ValueError):
        result.error(
            "E_TYPE",
            f"expected a number, got {type(value).__name__}",
            field=field,
        )
        return result

    if math.isnan(v) or math.isinf(v):
        result.error(code, f"value must be finite, got {v!r}", field=field)
        return result

    lo_ok = True
    hi_ok = True
    if lo is not None:
        lo_ok = (v >= lo) if lo_inclusive else (v > lo)
    if hi is not None:
        hi_ok = (v <= hi) if hi_inclusive else (v < hi)

    if not lo_ok or not hi_ok:
        lo_bracket = "[" if lo_inclusive else "("
        hi_bracket = "]" if hi_inclusive else ")"
        lo_str = "-∞" if lo is None else str(lo)
        hi_str = "+∞" if hi is None else str(hi)
        result.error(
            code,
            f"value {v!r} is outside {lo_bracket}{lo_str}, {hi_str}{hi_bracket}",
            field=field,
        )
    return result


def check_positive(
    value: Any,
    *,
    field: str | None = None,
    strict: bool = True,
    code: str = "E_NOT_POSITIVE",
) -> Result:
    """Check that *value* is > 0 (or >= 0 when *strict* is ``False``)."""
    return check_in_range(
        value,
        lo=0.0,
        lo_inclusive=not strict,
        field=field,
        code=code,
    )


def check_non_negative(value: Any, *, field: str | None = None) -> Result:
    """Check that *value* is >= 0."""
    return check_positive(value, field=field, strict=False, code="E_NEGATIVE")


# ---------------------------------------------------------------------------
# String checks
# ---------------------------------------------------------------------------


def check_non_empty_str(
    value: Any,
    *,
    field: str | None = None,
    strip: bool = True,
) -> Result:
    """Check that *value* is a non-empty (and, by default, non-blank) string."""
    result = Result()
    if not isinstance(value, str):
        result.error("E_TYPE", f"expected str, got {type(value).__name__}", field=field)
        return result
    text = value.strip() if strip else value
    if not text:
        result.error("E_EMPTY_STRING", "value must not be empty", field=field)
    return result


def check_str_length(
    value: Any,
    *,
    min_len: int = 0,
    max_len: int | None = None,
    field: str | None = None,
) -> Result:
    """Check that a string's length is within [*min_len*, *max_len*]."""
    result = Result()
    if not isinstance(value, str):
        result.error("E_TYPE", f"expected str, got {type(value).__name__}", field=field)
        return result
    n = len(value)
    if n < min_len:
        result.error(
            "E_STR_TOO_SHORT",
            f"string length {n} is below minimum {min_len}",
            field=field,
        )
    if max_len is not None and n > max_len:
        result.error(
            "E_STR_TOO_LONG",
            f"string length {n} exceeds maximum {max_len}",
            field=field,
        )
    return result


def check_enum_member(
    value: Any,
    choices: Sequence[Any],
    *,
    field: str | None = None,
    case_insensitive: bool = False,
) -> Result:
    """Check that *value* is one of *choices*."""
    result = Result()
    normalised = [str(c).casefold() for c in choices] if case_insensitive else list(choices)
    candidate = str(value).casefold() if case_insensitive else value
    if candidate not in normalised:
        quoted = ", ".join(repr(c) for c in choices)
        result.error(
            "E_INVALID_CHOICE",
            f"value {value!r} is not one of {{{quoted}}}",
            field=field,
        )
    return result


# ---------------------------------------------------------------------------
# Collection checks
# ---------------------------------------------------------------------------


def check_non_empty_seq(
    value: Any,
    *,
    field: str | None = None,
) -> Result:
    """Check that *value* is a non-empty sequence (list, tuple, etc.)."""
    result = Result()
    if not isinstance(value, (list, tuple, Sequence)) or isinstance(value, str):
        result.error("E_TYPE", f"expected a sequence, got {type(value).__name__}", field=field)
        return result
    if len(value) == 0:  # type: ignore[arg-type]
        result.error("E_EMPTY_SEQUENCE", "sequence must contain at least one element", field=field)
    return result


def check_unique(
    values: Sequence[Any],
    *,
    field: str | None = None,
    code: str = "E_DUPLICATE",
) -> Result:
    """Check that all elements in *values* are distinct."""
    result = Result()
    seen: dict[Any, int] = {}
    for item in values:
        seen[item] = seen.get(item, 0) + 1
    for item, count in seen.items():
        if count > 1:
            result.error(code, f"value {item!r} appears {count} times", field=field)
    return result


def check_no_duplicate_keys(
    mapping: dict[Any, Any],
    *,
    field: str | None = None,
) -> Result:
    """Check that a dict has no duplicate string keys (only relevant when
    loading from formats like JSON that technically allow them).

    In practice this is a no-op because Python dicts cannot have duplicate keys;
    the function exists so validation pipelines can reference it explicitly.
    """
    return check_unique(list(mapping.keys()), field=field, code="E_DUPLICATE_KEY")


# ---------------------------------------------------------------------------
# Mapping / schema checks
# ---------------------------------------------------------------------------


def check_required_keys(
    mapping: dict[str, Any],
    required: Sequence[str],
    *,
    field: str | None = None,
) -> Result:
    """Check that all *required* keys are present in *mapping*."""
    result = Result()
    for key in required:
        if key not in mapping:
            result.error(
                "E_MISSING_KEY",
                f"required key {key!r} is absent",
                field=f"{field}.{key}" if field else key,
            )
    return result


def check_no_extra_keys(
    mapping: dict[str, Any],
    allowed: Sequence[str],
    *,
    field: str | None = None,
) -> Result:
    """Check that *mapping* contains no keys outside of *allowed*."""
    result = Result()
    allowed_set = set(allowed)
    for key in mapping:
        if key not in allowed_set:
            result.error(
                "E_EXTRA_KEY",
                f"unexpected key {key!r}",
                field=f"{field}.{key}" if field else key,
            )
    return result


# ---------------------------------------------------------------------------
# Type-check helper
# ---------------------------------------------------------------------------


def check_is_type(
    value: Any,
    expected_type: type | tuple[type, ...],
    *,
    field: str | None = None,
) -> Result:
    """Check that *value* is an instance of *expected_type*."""
    result = Result()
    if not isinstance(value, expected_type):
        if isinstance(expected_type, tuple):
            type_names = " | ".join(t.__name__ for t in expected_type)
        else:
            type_names = expected_type.__name__
        result.error(
            "E_TYPE",
            f"expected {type_names}, got {type(value).__name__}",
            field=field,
        )
    return result


# ---------------------------------------------------------------------------
# SchemaValidator — fluent accumulator
# ---------------------------------------------------------------------------


class SchemaValidator:
    """Fluent helper that accumulates issues while validating a mapping.

    Typical usage::

        v = SchemaValidator(data, context="training config")
        v.require_keys(["batch_size", "learning_rate"])
        v.field("batch_size").positive_int()
        v.field("learning_rate").in_range(lo=1e-7, hi=1.0)
        v.result.raise_if_invalid()

    All ``check_*`` methods on :class:`_FieldChain` return the chain itself
    so calls can be chained, and append issues onto the parent
    :class:`SchemaValidator`'s :attr:`result`.
    """

    def __init__(
        self,
        data: dict[str, Any],
        *,
        context: str = "",
    ) -> None:
        self._data = data
        self._context = context
        self.result: Result = Result()

    def require_keys(self, keys: Sequence[str]) -> SchemaValidator:
        """Assert that all *keys* are present in the data mapping."""
        self.result.extend(
            check_required_keys(self._data, keys, field=self._context or None)
        )
        return self

    def no_extra_keys(self, allowed: Sequence[str]) -> SchemaValidator:
        """Assert that no keys outside *allowed* are present."""
        self.result.extend(
            check_no_extra_keys(self._data, allowed, field=self._context or None)
        )
        return self

    def field(self, name: str) -> _FieldChain:
        """Return a :class:`_FieldChain` for the field *name*."""
        dotted = f"{self._context}.{name}" if self._context else name
        value = self._data.get(name, _MISSING)
        return _FieldChain(self, dotted, value)

    def raise_if_invalid(
        self,
        exception_class: type[Exception] = DesignValidationError,
    ) -> None:
        """Raise *exception_class* if any errors were accumulated."""
        self.result.raise_if_invalid(exception_class)


class _FieldChain:
    """Chainable validator for a single field value."""

    def __init__(
        self,
        parent: SchemaValidator,
        dotted: str,
        value: Any,
    ) -> None:
        self._parent = parent
        self._dotted = dotted
        self._value = value

    def _add(self, r: Result) -> _FieldChain:
        self._parent.result.extend(r)
        return self

    def required(self) -> _FieldChain:
        """Flag the field as required (i.e. it must exist in the mapping)."""
        if self._value is _MISSING:
            self._parent.result.error(
                "E_MISSING_KEY",
                f"required field {self._dotted!r} is absent",
                field=self._dotted,
            )
        return self

    def optional(self) -> _FieldChain:
        """Mark the field as optional; skip subsequent checks if it is absent."""
        if self._value is _MISSING:
            # replace sentinel so chained checks become no-ops
            self._value = None
        return self

    def is_type(self, expected: type | tuple[type, ...]) -> _FieldChain:
        if self._value is _MISSING or self._value is None:
            return self
        return self._add(check_is_type(self._value, expected, field=self._dotted))

    def non_empty_str(self) -> _FieldChain:
        if self._value is _MISSING or self._value is None:
            return self
        return self._add(check_non_empty_str(self._value, field=self._dotted))

    def str_length(
        self,
        *,
        min_len: int = 0,
        max_len: int | None = None,
    ) -> _FieldChain:
        if self._value is _MISSING or self._value is None:
            return self
        return self._add(
            check_str_length(self._value, min_len=min_len, max_len=max_len, field=self._dotted)
        )

    def in_range(
        self,
        *,
        lo: float | None = None,
        hi: float | None = None,
        lo_inclusive: bool = True,
        hi_inclusive: bool = True,
    ) -> _FieldChain:
        if self._value is _MISSING or self._value is None:
            return self
        return self._add(
            check_in_range(
                self._value,
                lo=lo,
                hi=hi,
                lo_inclusive=lo_inclusive,
                hi_inclusive=hi_inclusive,
                field=self._dotted,
            )
        )

    def positive(self, *, strict: bool = True) -> _FieldChain:
        if self._value is _MISSING or self._value is None:
            return self
        return self._add(check_positive(self._value, field=self._dotted, strict=strict))

    def positive_int(self) -> _FieldChain:
        """Check that the field is a positive integer (> 0)."""
        if self._value is _MISSING or self._value is None:
            return self
        self._add(check_is_type(self._value, int, field=self._dotted))
        if isinstance(self._value, int):
            self._add(check_positive(self._value, field=self._dotted))
        return self

    def non_negative(self) -> _FieldChain:
        if self._value is _MISSING or self._value is None:
            return self
        return self._add(check_non_negative(self._value, field=self._dotted))

    def one_of(
        self,
        choices: Sequence[Any],
        *,
        case_insensitive: bool = False,
    ) -> _FieldChain:
        if self._value is _MISSING or self._value is None:
            return self
        return self._add(
            check_enum_member(
                self._value,
                choices,
                field=self._dotted,
                case_insensitive=case_insensitive,
            )
        )


# ---------------------------------------------------------------------------
# Convenience assertion wrappers (raise immediately on first failure)
# ---------------------------------------------------------------------------


def _raise_from(result: Result, exc: type[Exception] = DesignValidationError) -> None:
    result.raise_if_invalid(exc)


def assert_in_range(
    value: Any,
    *,
    lo: float | None = None,
    hi: float | None = None,
    lo_inclusive: bool = True,
    hi_inclusive: bool = True,
    field: str | None = None,
) -> None:
    """Like :func:`check_in_range` but raises on failure."""
    _raise_from(
        check_in_range(
            value,
            lo=lo,
            hi=hi,
            lo_inclusive=lo_inclusive,
            hi_inclusive=hi_inclusive,
            field=field,
        )
    )


def assert_positive(
    value: Any,
    *,
    field: str | None = None,
    strict: bool = True,
) -> None:
    """Like :func:`check_positive` but raises on failure."""
    _raise_from(check_positive(value, field=field, strict=strict))


def assert_non_negative(value: Any, *, field: str | None = None) -> None:
    """Like :func:`check_non_negative` but raises on failure."""
    _raise_from(check_non_negative(value, field=field))


def assert_non_empty_str(
    value: Any,
    *,
    field: str | None = None,
    strip: bool = True,
) -> None:
    """Like :func:`check_non_empty_str` but raises on failure."""
    _raise_from(check_non_empty_str(value, field=field, strip=strip))


def assert_required_keys(
    mapping: dict[str, Any],
    required: Sequence[str],
    *,
    field: str | None = None,
) -> None:
    """Like :func:`check_required_keys` but raises on failure."""
    _raise_from(check_required_keys(mapping, required, field=field))


__all__ = [
    # types
    "ValidationSeverity",
    "Issue",
    "Result",
    # scalar checks
    "check_in_range",
    "check_positive",
    "check_non_negative",
    # string checks
    "check_non_empty_str",
    "check_str_length",
    "check_enum_member",
    # collection checks
    "check_non_empty_seq",
    "check_unique",
    "check_no_duplicate_keys",
    # mapping checks
    "check_required_keys",
    "check_no_extra_keys",
    # type check
    "check_is_type",
    # fluent validator
    "SchemaValidator",
    # assertion shortcuts
    "assert_in_range",
    "assert_positive",
    "assert_non_negative",
    "assert_non_empty_str",
    "assert_required_keys",
]
