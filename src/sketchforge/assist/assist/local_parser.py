"""The local, rule-based instruction parser: the no-network baseline planner.

It understands a deliberately small, documented slice of English ("make the second input wider",
"change the button text to 'Log in'", "move the heading down 20 px", "center the card"). It either
returns a plan it is sure about or says *why not*; it never guesses between candidates. An
ambiguous reference ("the button" when there are three) is a refusal, not a coin flip, because a
wrong edit is worse than a question.

Supported (see ``docs/EDIT_ASSISTANT.md`` for the grammar):

* references: component id (``button-1``), type word (button, input/field, heading/title,
  text/label, card, header, ...), ordinal (first, second, last, ``#2``), position (top, bottom,
  left, right, middle), quoted text (``the 'Submit' button``), colour, ``it``/``them`` for the
  previous clause's target, and ``all``/plural for every match;
* actions: set text (quote the new text), fill / text / border colour, move by a distance, set
  position, centre, resize (wider / narrower / taller / shorter / bigger / smaller, absolute
  sizes), font size, corner radius, add a border.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sketchforge.assist.edit_plan import (
    COLOR_NAMES,
    MAX_OPS,
    EditOp,
    EditPlan,
    Grow,
    Move,
    Resize,
    SetBorder,
    SetCornerRadius,
    SetFill,
    SetFontSize,
    SetPosition,
    SetText,
    SetTextColor,
    resolve_color,
)
from sketchforge.design_ir.schema import Component, ComponentType, DesignDocument
from sketchforge.exceptions import EditError

T = ComponentType

TYPE_WORDS: dict[str, ComponentType] = {
    "text field": T.INPUT, "text box": T.INPUT, "textbox": T.INPUT, "textfield": T.INPUT,
    "input field": T.INPUT, "input box": T.INPUT, "input": T.INPUT, "field": T.INPUT,
    "radio button": T.RADIO, "radio": T.RADIO, "checkbox": T.CHECKBOX, "check box": T.CHECKBOX,
    "button": T.BUTTON, "cta": T.BUTTON,
    "heading": T.HEADING, "headline": T.HEADING, "title": T.HEADING,
    "paragraph": T.TEXT, "caption": T.TEXT, "label": T.TEXT, "text": T.TEXT,
    "header": T.HEADER, "navbar": T.HEADER, "nav bar": T.HEADER, "top bar": T.HEADER,
    "sidebar": T.SIDEBAR, "footer": T.FOOTER,
    "card": T.CARD, "panel": T.CARD, "container": T.CONTAINER, "section": T.CONTAINER,
    "image": T.IMAGE, "picture": T.IMAGE, "photo": T.IMAGE, "avatar": T.IMAGE, "logo": T.IMAGE,
    "divider": T.DIVIDER, "separator": T.DIVIDER, "line": T.DIVIDER,
}
_TYPE_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(w) for w in TYPE_WORDS), key=len, reverse=True)) + r")(s|es)?\b")
_COLOR_RE = re.compile(
    r"(?<![\w#])(#[0-9a-f]{6}|#[0-9a-f]{3}|" + "|".join(
        sorted((re.escape(w) for w in COLOR_NAMES), key=len, reverse=True)) + r")\b")
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
             "fifth": 5, "5th": 5, "last": -1, "final": -1}
_POSITIONS = {"top", "topmost", "upper", "bottom", "bottommost", "lower", "left", "leftmost", "right",
              "rightmost", "middle", "center", "centre"}
_QUANT = {"all", "every", "each", "both"}
_BOUNDARY = {"make", "change", "set", "turn", "move", "resize", "color", "colour", "paint", "give", "update",
             "rename", "relabel", "put", "center", "centre", "round", "increase", "decrease", "shrink",
             "enlarge", "widen", "nudge", "shift", "of", "for", "to", "on", "in", "at", "with", "and", "then",
             "push", "slide", "bump", "add", "fill", "grow", "bigger", "larger", "smaller", "wider", "taller"}
_FILLER = {"the", "a", "an", "this", "that", "these", "those", "my", "our", "your", "its", "it", "main",
           "primary", "secondary", "big", "small", "large", "new", "current", "whole", "entire", "same",
           "page", "form", "one", "only", "single", "other", "another", "please", "also", "just"}
_PRONOUNS = {"it", "them", "that", "this", "those", "these", "they"}
_UNSUPPORTED = re.compile(r"\b(delete|remove|hide|duplicate|clone|add a new|insert|create|swap|reorder|animate)\b")
_TEXT_WORDS = {"text", "font", "label", "letters", "lettering", "caption", "words", "writing"}
_DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_NUM = r"(\d+(?:\.\d+)?)"
_MAX_TARGETS = MAX_OPS


@dataclass(frozen=True)
class ParseResult:
    """Either a plan or the reason there is none. ``kind`` is ``ok`` or one of
    ``ambiguous`` / ``no_target`` / ``unsupported`` / ``unparsed``."""

    plan: EditPlan | None
    reason: str | None = None
    kind: str = "ok"
    clauses: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.plan is not None


class _Refuse(Exception):
    def __init__(self, kind: str, reason: str, targets: list | None = None) -> None:
        super().__init__(reason)
        self.kind = kind
        self.reason = reason
        self.targets = targets or []  # components a clause named even though it asked for nothing


@dataclass
class _Ctx:
    doc: DesignDocument
    quotes: list[str]
    last: list[Component] = field(default_factory=list)
    used_quotes: set[int] = field(default_factory=set)
    pending: list[Component] = field(default_factory=list)  # named by an earlier action-less clause


# ---------------------------------------------------------------------------------- tokenising
_QUOTE_RE = re.compile(r'"([^"]*)"|“([^”]*)”|(?<![A-Za-z0-9])\'([^\']*)\'(?![A-Za-z0-9])')


def _mask_quotes(text: str) -> tuple[str, list[str]]:
    quotes: list[str] = []

    def sub(m: re.Match[str]) -> str:
        quotes.append(next(g for g in m.groups() if g is not None))
        return f" __q{len(quotes) - 1}__ "

    return _QUOTE_RE.sub(sub, text), quotes


_SPLIT_RE = re.compile(r"\s*(?:;|,\s*and then\b|\band then\b|\bthen\b|,\s*and\b|\band\b)\s*", re.IGNORECASE)


def _clauses(masked: str) -> list[tuple[str, str]]:
    """(lower-case clause, original-case clause) pairs, quotes still masked."""
    pieces = [c.strip(" ,.") for c in _SPLIT_RE.split(masked) if c.strip(" ,.")]
    return [(c.lower(), c) for c in pieces]


# ---------------------------------------------------------------------------------- targets
def _candidates(doc: DesignDocument, ctype: ComponentType) -> list[Component]:
    found = [c for c in doc.components if c.id != doc.root_id and c.type is ctype and c.visible]
    return sorted(found, key=lambda c: (round(c.bbox.y / 10), c.bbox.x))


def _find_type_match(clause: str) -> re.Match[str] | None:
    """The first type word that is the *subject* rather than an attribute ("button text", "text of")."""
    for m in _TYPE_RE.finditer(clause):
        word = m.group(1)
        before = clause[: m.start()]
        # "text of the button" / "color of the card": the attribute word precedes "of|for|on".
        if re.match(r"\s*(?:of|for|on)\b", clause[m.end():]) and word in _TEXT_WORDS:
            continue
        # "button text", "heading label": an attribute following an earlier type word.
        if word in _TEXT_WORDS and _TYPE_RE.search(before) and not re.search(r"\b(?:make|set|turn|change)\s+(?:the\s+)?$", before):
            continue
        # "text color", "font size": the word modifies colour/size, not a component.
        if word in {"text", "label"} and re.match(r"\s*(?:colou?r|size|weight)\b", clause[m.end():]):
            continue
        return m
    return None


def _window(clause: str, start: int) -> tuple[list[str], int]:
    """Words directly before the type word, back to the nearest verb/preposition."""
    words = clause[:start].split()
    out: list[str] = []
    i = len(words) - 1
    while i >= 0 and words[i] not in _BOUNDARY:
        out.append(words[i])
        i -= 1
    out.reverse()
    first = len(" ".join(words[: i + 1])) + (1 if i >= 0 else 0)
    return out, first


def _narrow_position(cands: list[Component], pos: str) -> list[Component]:
    if not cands:
        return cands
    if pos in ("top", "topmost", "upper"):
        best = min(c.bbox.y for c in cands)
        return [c for c in cands if abs(c.bbox.y - best) < 10]
    if pos in ("bottom", "bottommost", "lower"):
        best = max(c.bbox.y + c.bbox.h for c in cands)
        return [c for c in cands if abs(c.bbox.y + c.bbox.h - best) < 10]
    if pos in ("left", "leftmost"):
        best = min(c.bbox.x for c in cands)
        return [c for c in cands if abs(c.bbox.x - best) < 10]
    if pos in ("right", "rightmost"):
        best = max(c.bbox.x + c.bbox.w for c in cands)
        return [c for c in cands if abs(c.bbox.x + c.bbox.w - best) < 10]
    ordered = sorted(cands, key=lambda c: (c.bbox.y, c.bbox.x))  # middle / center
    if len(ordered) % 2 == 1:
        return [ordered[len(ordered) // 2]]
    return ordered[len(ordered) // 2 - 1: len(ordered) // 2 + 1]


def _inside(doc: DesignDocument, comp: Component, ancestor_id: str) -> bool:
    seen = 0
    cur = comp
    while cur.parent_id and seen < 64:
        if cur.parent_id == ancestor_id:
            return True
        cur = doc.get(cur.parent_id) or cur
        if cur.parent_id is None:
            break
        seen += 1
    return False


def _color_of(word: str) -> str:
    return resolve_color(word)


def _resolve_targets(clause: str, ctx: _Ctx) -> tuple[list[Component], str, bool]:
    """-> (targets, clause with the reference blanked out, the reference was about the text)."""
    doc = ctx.doc
    # 1. exact component id
    for m in re.finditer(r"\b[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*-\d+\b", clause):
        comp = doc.get(m.group(0))
        if comp is not None and comp.id != doc.root_id:
            rest = clause[: m.start()] + " " * (m.end() - m.start()) + clause[m.end():]
            return [comp], rest, False

    match = _find_type_match(clause)
    if match is None:
        if _PRONOUNS & set(clause.split()) or ctx.last:
            if not ctx.last:
                raise _Refuse("no_target", "'it'/'them' used but there is no earlier target")
            rest = re.sub(r"\b(?:it|them|that|this|those|these|they)\b", " ", clause)
            return list(ctx.last), rest, False
        raise _Refuse("no_target", "no component is mentioned (use a type like 'button', an id like 'button-1', "
                                   "or 'it' for the previous one)")

    ctype = TYPE_WORDS[match.group(1)]
    plural = bool(match.group(2))
    window, wstart = _window(clause, match.start())
    after = clause[match.end():]

    cands = _candidates(doc, ctype)
    if not cands:
        raise _Refuse("no_target", f"the design has no {ctype.value}")

    allq = plural or bool(_QUANT & set(window)) or bool(re.match(r"\s*(?:are|all)\b", after))
    ordinal: int | None = None
    positions: list[str] = []
    hints: list[str] = []
    colors: list[str] = []
    quoted: list[int] = []
    for w in window:
        mq = re.fullmatch(r"__q(\d+)__", w)
        if mq:
            quoted.append(int(mq.group(1)))
        elif w in _ORDINALS:
            ordinal = _ORDINALS[w]
        elif w in _POSITIONS:
            positions.append(w)
        elif w in _QUANT or w in _FILLER:
            continue
        elif _COLOR_RE.fullmatch(w):
            colors.append(w)
        elif w.isdigit():
            continue
        else:
            hints.append(w)
    mnum = re.match(r"\s*(?:#|number\s+|no\.?\s*)(\d+)\b", after)
    if mnum:
        ordinal = int(mnum.group(1))
        after = after[mnum.end():]
    mpos = re.match(r"\s*(?:at|on|in|near)\s+the\s+(top|bottom|left|right|middle|center|centre)\b", after)
    if mpos:
        positions.append(mpos.group(1))

    # trailing "<type> text|label" marks "the text of that component" (colour/size apply to the text)
    about_text = bool(re.match(r"\s*(?:text|label|caption|font|letters|words)\b", after)) or \
        bool(re.search(r"\b(?:text|font|label)\s+(?:colou?r|size)\b", clause))
    if re.search(r"\b(?:text|label|caption)\s+of\s+(?:the\s+)?\w*$", clause[: match.start()] + " "):
        about_text = True

    pool = list(cands)
    scope_end = 0
    mscope = re.match(r"\s*(?:in|inside|within|of)\s+the\s+(?:(first|second|third|last)\s+)?"
                      r"(card|header|sidebar|footer|container|panel|section)s?\b", after)
    if mscope and TYPE_WORDS[mscope.group(2)] in (T.CARD, T.HEADER, T.SIDEBAR, T.FOOTER, T.CONTAINER):
        scopes = _candidates(doc, TYPE_WORDS[mscope.group(2)])
        if mscope.group(1):
            idx = _ORDINALS[mscope.group(1)]
            idx = idx - 1 if idx > 0 else len(scopes) + idx
            scopes = [scopes[idx]] if 0 <= idx < len(scopes) else []
        if len(scopes) != 1:
            raise _Refuse("ambiguous" if scopes else "no_target",
                          f"'{mscope.group(2)}' matches {len(scopes)} components; say which (first/second/last)")
        keep = [c for c in pool if _inside(doc, c, scopes[0].id)]
        if not keep:
            raise _Refuse("no_target", f"no {ctype.value} inside {scopes[0].id}")
        pool = keep
        scope_end = mscope.end()
    for q in quoted:
        ctx.used_quotes.add(q)
        want = ctx.quotes[q].strip().lower()
        pool = [c for c in pool if (c.text or "").strip().lower() == want or (c.name or "").lower() == want]
        if not pool:
            raise _Refuse("no_target", f"no {ctype.value} has the text {ctx.quotes[q]!r}")
    for h in hints:
        keep = [c for c in pool if h in (c.text or "").lower() or h in (c.name or "").lower()]
        if not keep:
            raise _Refuse("no_target", f"no {ctype.value} matches {h!r}")
        pool = keep
    for col in colors:
        want = _color_of(col)
        keep = [c for c in pool if c.style.fill.lower() == want or (c.typography and c.typography.color.lower() == want)]
        if not keep:
            raise _Refuse("no_target", f"no {ctype.value} is {col}")
        pool = keep
    for pos in positions:
        pool = _narrow_position(pool, pos)
    if ordinal is not None:
        index = ordinal - 1 if ordinal > 0 else len(pool) + ordinal
        if not 0 <= index < len(pool):
            raise _Refuse("no_target", f"there is no {ordinal}{'st' if ordinal == 1 else 'th'} {ctype.value} "
                                       f"(found {len(pool)})")
        pool = [pool[index]]
    if len(pool) > 1 and not allq:
        ids = ", ".join(c.id for c in pool[:6])
        raise _Refuse("ambiguous", f"'{ctype.value}' matches {len(pool)} components ({ids}); say which one "
                                   "(first/second/last, top/bottom, its text in quotes, or its id)")
    if len(pool) > _MAX_TARGETS:
        raise _Refuse("unsupported", f"that matches {len(pool)} components; at most {_MAX_TARGETS} per edit")

    end = match.end() + (mnum.end() if mnum else 0) + scope_end
    rest = clause[:wstart] + " " * (end - wstart) + clause[end:]
    return pool, rest, about_text


# ---------------------------------------------------------------------------------- actions
def _number(s: str) -> float:
    return float(s)


def _text_op(rest: str, original_rest: str, ctx: _Ctx, targets: list[Component]) -> list[EditOp] | None:
    left = [i for i in range(len(ctx.quotes)) if i not in ctx.used_quotes and f"__q{i}__" in rest]
    verb = re.search(r"\b(change|set|rename|relabel|replace|update|say|says|read|reads|write|make|label|title)\b", rest)
    if left and verb:
        ctx.used_quotes.add(left[0])
        text = ctx.quotes[left[0]]
        ops: list[EditOp] = []
        for t in targets:
            ops.append(SetText(op="set_text", target=t.id, text=text))
        return ops
    m = re.search(r"\b(?:text|label|caption|title|heading)\s+(?:to|as)\s+(.+)$", original_rest, re.IGNORECASE)
    m = m or re.search(r"\b(?:rename|relabel)\b.*?\bto\s+(.+)$", original_rest, re.IGNORECASE)
    if m and not _COLOR_RE.fullmatch(m.group(1).strip().lower()) and not re.fullmatch(r"[\d\s.,pxPX%]+", m.group(1)):
        return [SetText(op="set_text", target=t.id, text=m.group(1).strip(" .\"'")) for t in targets]
    return None


def _color_ops(rest: str, targets: list[Component], about_text: bool) -> list[EditOp] | None:
    colors = [m.group(1) for m in _COLOR_RE.finditer(rest)]
    if not colors:
        return None
    resolved = {_color_of(c) for c in colors}
    if len(resolved) > 1:
        raise _Refuse("unsupported", "two different colours in one clause; give one colour per instruction")
    color = colors[0]
    wants_border = bool(re.search(r"\b(?:border|outline|stroke)\b", rest))
    wants_text = about_text or bool(_TEXT_WORDS & set(re.findall(r"[a-z]+", rest)))
    wants_fill = bool(re.search(r"\b(?:background|fill|bg)\b", rest))
    ops: list[EditOp] = []
    for t in targets:
        if wants_border:
            ops.append(SetBorder(op="set_border", target=t.id, color=color))
        elif wants_fill:
            ops.append(SetFill(op="set_fill", target=t.id, color=color))
        elif wants_text or t.type in (T.TEXT, T.HEADING):
            ops.append(SetTextColor(op="set_text_color", target=t.id, color=color))
        else:
            ops.append(SetFill(op="set_fill", target=t.id, color=color))
    return ops


def _move_ops(rest: str, targets: list[Component], doc: DesignDocument, inherited: bool) -> list[EditOp] | None:
    ops: list[EditOp] = []
    mv = re.search(r"\b(?:move|shift|nudge|push|slide|bump)\b", rest) or inherited
    if re.search(r"\bcent(?:er|re)\b", rest):
        horiz = "vertical" not in rest or "horizontal" in rest or "both" in rest
        vert = "vertical" in rest or "both" in rest
        for t in targets:
            parent = doc.get(t.parent_id) if t.parent_id else None
            frame = parent.bbox if parent is not None else None
            fw = frame.w if frame else doc.page.width
            fh = frame.h if frame else doc.page.height
            fx = frame.x if frame else 0.0
            fy = frame.y if frame else 0.0
            ops.append(SetPosition(
                op="set_position", target=t.id,
                x=round(fx + (fw - t.bbox.w) / 2, 1) if horiz else None,
                y=round(fy + (fh - t.bbox.h) / 2, 1) if vert else None))
        return ops
    mabs = re.search(r"\b(?:to|at)\s*\(?\s*" + _NUM + r"\s*,\s*" + _NUM + r"\s*\)?", rest)
    if mabs and (mv or "put" in rest or "position" in rest):
        for t in targets:
            ops.append(SetPosition(op="set_position", target=t.id, x=_number(mabs.group(1)), y=_number(mabs.group(2))))
        return ops
    mx = re.search(r"\bx\s*(?:=|to|at|of)?\s*" + _NUM + r"\b", rest)
    my = re.search(r"\by\s*(?:=|to|at|of)?\s*" + _NUM + r"\b", rest)
    if (mx or my) and not re.search(r"\b(?:width|height)\b", rest):
        for t in targets:
            ops.append(SetPosition(op="set_position", target=t.id, x=_number(mx.group(1)) if mx else None,
                                   y=_number(my.group(1)) if my else None))
        return ops
    dirs = [(m.group(1), m.start()) for m in re.finditer(r"\b(up|down|left|right)(?:ward)?s?\b", rest)]
    if dirs and mv:
        if re.search(r"\b(?:of|from)\s+(?:the\s+)?(?:\w+\s+)?(?:button|input|field|card|heading|header|text|image)\b", rest):
            raise _Refuse("unsupported", "positioning relative to another component is not supported; "
                                         "give a distance or coordinates")
        mn = re.search(_NUM + r"\s*(?:px|pixels?)?", rest)
        if not mn:
            raise _Refuse("unsupported", "no distance given (e.g. 'move the button down 20 px')")
        name = dirs[0][0]
        sx, sy = _DIRS[name]
        dist = _number(mn.group(1))
        return [Move(op="move", target=t.id, dx=sx * dist, dy=sy * dist) for t in targets]
    return None


def _size_ops(rest: str, targets: list[Component], about_text: bool) -> list[EditOp] | None:
    ops: list[EditOp] = []
    mabs2 = re.search(_NUM + r"\s*(?:px)?\s*(?:x|by|×)\s*" + _NUM, rest)
    if mabs2 and re.search(r"\b(?:resize|size|make|set)\b", rest) and "font" not in rest:
        return [Resize(op="resize", target=t.id, width=_number(mabs2.group(1)), height=_number(mabs2.group(2))) for t in targets]
    mw = re.search(r"\bwidth\b\D{0,24}?" + _NUM, rest) or re.search(_NUM + r"\s*(?:px|pixels?)?\s*wide\b", rest)
    mh = re.search(r"\bheight\b\D{0,24}?" + _NUM, rest) or re.search(_NUM + r"\s*(?:px|pixels?)?\s*(?:tall|high)\b", rest)
    if mw or mh:
        return [Resize(op="resize", target=t.id, width=_number(mw.group(1)) if mw else None,
                       height=_number(mh.group(1)) if mh else None) for t in targets]
    mf = re.search(r"\b(twice|double|half|triple)\b(?:\s+as)?(?:\s+the)?\s+(wide|width|tall|height|high|big|large|size)", rest)
    mword = re.search(r"\b(wider|broader|narrower|taller|shorter|bigger|larger|smaller|widen|enlarge|shrink)\b", rest)
    if mf:
        factor = {"twice": 2.0, "double": 2.0, "half": 0.5, "triple": 3.0}[mf.group(1)]
        dim = mf.group(2)
        for t in targets:
            b = t.bbox
            dw = (factor - 1) * b.w if dim in ("wide", "width", "big", "large", "size") else 0.0
            dh = (factor - 1) * b.h if dim in ("tall", "height", "high", "big", "large", "size") else 0.0
            ops.append(Grow(op="grow", target=t.id, dw=round(dw, 1), dh=round(dh, 1)))
        return ops
    if mword and not (about_text and mword.group(1) in ("bigger", "larger", "smaller", "enlarge", "shrink")):
        w = mword.group(1)
        mby = (re.search(r"\bby\s*" + _NUM + r"\s*(%|px|pixels?)?", rest)
               or re.search(_NUM + r"\s*(%|px|pixels?)\s*(?:\w+\s+)?" + w + r"\b", rest))
        sign = -1 if w in ("narrower", "shorter", "smaller", "shrink") else 1
        horiz = w in ("wider", "broader", "narrower", "widen")
        vert = w in ("taller", "shorter")
        both = w in ("bigger", "larger", "smaller", "enlarge", "shrink")
        for t in targets:
            if t.type in (T.TEXT, T.HEADING) and both:
                continue  # handled as a font-size change
            b = t.bbox
            if mby:
                amount = _number(mby.group(1))
                pct = mby.group(2) == "%"
                dw = sign * (b.w * amount / 100 if pct else amount)
                dh = sign * (b.h * amount / 100 if pct else amount)
            else:
                dw, dh = sign * round(b.w * 0.2), sign * round(b.h * 0.2)
            ops.append(Grow(op="grow", target=t.id, dw=float(dw) if (horiz or both) else 0.0,
                            dh=float(dh) if (vert or both) else 0.0))
        return ops or None
    return None


def _font_ops(rest: str, targets: list[Component], about_text: bool) -> list[EditOp] | None:
    msize = re.search(r"\b(?:font|text)\s*size\b.*?" + _NUM, rest) or re.search(_NUM + r"\s*(?:px|pt)\s*(?:font|text)\b", rest)
    if msize:
        return [SetFontSize(op="set_font_size", target=t.id, size=_number(msize.group(1))) for t in targets if t.typography]
    mword = re.search(r"\b(bigger|larger|smaller|increase|decrease|enlarge|shrink)\b", rest)
    if mword and (about_text or all(t.type in (T.TEXT, T.HEADING) for t in targets)):
        up = mword.group(1) in ("bigger", "larger", "increase", "enlarge")
        ops: list[EditOp] = []
        for t in targets:
            if t.typography is None:
                continue
            size = t.typography.font_size
            ops.append(SetFontSize(op="set_font_size", target=t.id,
                                   size=round(min(200, size * 1.25) if up else max(6, size / 1.25), 1)))
        return ops
    return None


def _corner_ops(rest: str, targets: list[Component]) -> list[EditOp] | None:
    if re.search(r"\b(?:square|sharp)\s+corners?\b|\bno\s+(?:rounded\s+)?corners?\b|\bsquare\s+off\b", rest):
        return [SetCornerRadius(op="set_corner_radius", target=t.id, radius=0) for t in targets]
    if not re.search(r"\b(?:round(?:ed|er)?|pill)\b", rest):
        return None
    mrad = re.search(r"\b(?:radius|to)\s*" + _NUM, rest)
    ops: list[EditOp] = []
    for t in targets:
        if "pill" in rest or "fully" in rest:
            radius = t.bbox.h / 2
        elif mrad:
            radius = _number(mrad.group(1))
        else:
            radius = max(8.0, t.style.corner_radius * 1.5 + (4.0 if "more" in rest or "rounder" in rest else 0.0))
        ops.append(SetCornerRadius(op="set_corner_radius", target=t.id, radius=round(radius, 1)))
    return ops


def _border_ops(rest: str, targets: list[Component]) -> list[EditOp] | None:
    if re.search(r"\b(?:add|give|put|draw)\b.*\b(?:border|outline)\b", rest) and not _COLOR_RE.search(rest):
        return [SetBorder(op="set_border", target=t.id, color="gray") for t in targets]
    return None


def _parse_clause(clause: str, original: str, ctx: _Ctx, first: bool) -> list[EditOp]:
    if _UNSUPPORTED.search(clause):
        raise _Refuse("unsupported", f"'{clause}': adding, removing or hiding components is not an edit this "
                                     "assistant can plan (it can change text, colour, position, size, font size, corners)")
    targets, rest, about_text = _resolve_targets(clause, ctx)
    inherited = bool(ctx.last) and targets == ctx.last and not first and not _find_type_match(clause)
    if ctx.pending:  # "make the heading and the button red": both clauses share the action
        targets = [*ctx.pending, *(t for t in targets if t not in ctx.pending)]
        ctx.pending = []
        if len(targets) > _MAX_TARGETS:
            raise _Refuse("unsupported", f"that names {len(targets)} components; at most {_MAX_TARGETS} per edit")
    for handler in (
        lambda: _text_op(rest, original, ctx, targets),
        lambda: _corner_ops(rest, targets),
        lambda: _font_ops(rest, targets, about_text),
        lambda: _size_ops(rest, targets, about_text),
        lambda: _move_ops(rest, targets, ctx.doc, inherited),
        lambda: _border_ops(rest, targets),
        lambda: _color_ops(rest, targets, about_text),
    ):
        ops = handler()
        if ops:
            ctx.last = list(targets)
            return ops
    raise _Refuse("unparsed", f"could not tell what to change in '{clause}'", targets)


def parse_instruction(text: str, doc: DesignDocument) -> ParseResult:
    """Turn one instruction (possibly several clauses) into an :class:`EditPlan`, or say why not."""
    text = (text or "").strip()
    if not text:
        return ParseResult(None, "empty instruction", "unparsed")
    if len(text) > 400:
        return ParseResult(None, "instruction is longer than 400 characters", "unparsed")
    masked, quotes = _mask_quotes(text)
    clauses = _clauses(masked)
    ctx = _Ctx(doc=doc, quotes=quotes)
    ops: list[EditOp] = []
    try:
        for i, (clause, original) in enumerate(clauses):
            try:
                ops.extend(_parse_clause(clause, original, ctx, first=(i == 0)))
            except _Refuse as r:
                if r.kind == "unparsed" and r.targets and i < len(clauses) - 1:
                    ctx.pending = list(r.targets)  # the next clause supplies the action
                    continue
                raise
        if not ops:
            raise _Refuse("unparsed", "nothing to do")
        if len(ops) > MAX_OPS:
            raise _Refuse("unsupported", f"that needs {len(ops)} operations; at most {MAX_OPS} per edit")
        return ParseResult(EditPlan(ops=ops, explanation=f"local parser: {text[:120]}"), None, "ok",
                           tuple(c for c, _ in clauses))
    except _Refuse as r:
        return ParseResult(None, r.reason, r.kind, tuple(c for c, _ in clauses))
    except (EditError, ValueError) as exc:
        return ParseResult(None, str(exc), "unparsed", tuple(c for c, _ in clauses))
