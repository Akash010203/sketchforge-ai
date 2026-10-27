"""Text measurement and placeholder text.

Real font metrics need a font engine; the evaluator, renderer and IR builder all need *one*
consistent estimate instead, so they share this. The width model is a deliberate approximation
(average advance of a proportional sans-serif) and is documented as such in docs/EVALUATION.md.
"""

from __future__ import annotations

import math

AVG_CHAR_EM = 0.55  # average advance of mixed-case Latin text in a sans-serif, in em
BOLD_EXTRA_PER_100 = 0.015  # extra advance per 100 weight units above 400

_FILLER = ["Lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit", "sed", "do", "eiusmod", "tempor", "incididunt", "ut", "labore", "et", "dolore", "magna", "aliqua", "ut", "enim", "ad", "minim", "veniam", "quis", "nostrud"]

_HEADINGS = ("Page title", "Welcome back", "Section heading", "Dashboard overview",
             "Account settings and preferences")
# Shorter whole-word fallbacks, so a narrow box never gets a word cut in half ("Page titl").
_SHORT = {"heading": ("Title", "Page", "Home", "Hi"), "button": ("Button", "Submit", "Go", "OK"),
          "input": ("Enter text", "Name", "Text"), "text": ()}


def _fit_whole(candidates: tuple[str, ...], budget: int) -> str | None:
    """The longest candidate that fits ``budget`` characters, or None."""
    fitting = [c for c in candidates if len(c) <= budget]
    return max(fitting, key=len) if fitting else None


def char_width(font_size: float, weight: int = 400) -> float:
    return font_size * (AVG_CHAR_EM + BOLD_EXTRA_PER_100 * max(0, weight - 400) / 100.0)


def estimate_text_width(text: str, font_size: float, weight: int = 400) -> float:
    return len(text) * char_width(font_size, weight)


def line_box_height(font_size: float, line_height: float) -> float:
    return font_size * line_height


def chars_that_fit(width: float, font_size: float, weight: int = 400) -> int:
    return max(0, int(math.floor(width / char_width(font_size, weight))))


def placeholder_for(kind: str, width: float, font_size: float, weight: int = 400) -> str:
    """Deterministic filler text sized to roughly fill ``width``.

    Sketch text is scribble, so its content is unknown; whatever is returned here must be stored
    with ``text_is_inferred=True`` so no later stage mistakes it for the user's words.
    """
    budget = chars_that_fit(width * 0.96, font_size, weight)
    if kind in ("button", "input", "heading"):
        primary = {"button": ("Button",), "input": ("Enter text",), "heading": _HEADINGS}[kind]
        pick = _fit_whole((*primary, *_SHORT[kind]), budget)
        return pick if pick is not None else "…"
    words: list[str] = []
    used = 0
    for word in _FILLER * 4:
        extra = len(word) + (1 if words else 0)
        if used + extra > budget:
            break
        words.append(word)
        used += extra
    if not words:
        shortest = min(_FILLER, key=len)
        return shortest.capitalize() if len(shortest) <= budget else "…"
    text = " ".join(words)
    return text[0].upper() + text[1:]
