"""Structured answers and grounding validation (T11.5).

The model finishes a turn by calling ``final_answer`` with typed blocks. The server:

* resolves metric and comparison cards from canonical services (the model never
  supplies a rendered value),
* rejects references to IDs that no tool returned in this turn (or the pinned context),
* checks every analytical number in prose against the numbers the tools returned,
  with unit scaling (lakh/crore/million, t, %) and the written rounding,
* refuses plan metrics for runs without a plan (INFEASIBLE/UNKNOWN/invalid).

Failures go back to the model once for a corrected answer; anything still unsupported
is replaced with an explicit "withheld" sentence plus the authoritative cards.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field

from aabflow.copilot.registry import ToolArgs, strict_schema

# ------------------------------------------------------------------ answer schema


class AnswerBlock(ToolArgs):
    type: Literal["text", "metric", "comparison", "action", "uncertainty"]
    text: str | None = Field(
        None, description="Prose for text/uncertainty blocks (in the answer language)"
    )
    citations: list[str] | None = Field(
        None, description="Run, evidence, analysis or comparison IDs this text uses"
    )
    metric_id: str | None = Field(None, description="metric block: metric ID from a tool result")
    run_id: str | None = Field(None, description="metric block: the run the metric belongs to")
    field_id: str | None = Field(
        None, description="metric block: field for field-level metrics, else null"
    )
    comparison_id: str | None = Field(
        None, description="comparison block: comparison_id from compare_runs"
    )
    action: (
        Literal[
            "open_run",
            "open_branch",
            "open_field",
            "open_report",
            "open_analysis",
            "open_comparison",
        ]
        | None
    ) = None
    ref_id: str | None = Field(None, description="action block: the ID to open")
    label: str | None = Field(None, description="action block: short button label")


class FinalAnswer(ToolArgs):
    language: Literal["en", "ur", "roman_ur"]
    blocks: list[AnswerBlock]
    needs_clarification: bool = Field(
        description="True when one focused question must be answered first"
    )
    clarification_question: str | None = None


FINAL_ANSWER_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "final_answer",
    "description": (
        "Finish the turn. Text blocks explain results in the user's language and cite the run/evidence IDs "
        "they rely on. Use metric blocks (metric_id + run_id [+ field_id]) and comparison blocks "
        "(comparison_id) for quantities: the server renders their values. Only quote numbers that appear in "
        "tool results; never compute new figures. Use uncertainty blocks for limitations, missing data, "
        "UNKNOWN/INFEASIBLE status or running jobs. Set needs_clarification with one question when an amount, "
        "currency or service floor is ambiguous."
    ),
    "strict": True,
    "parameters": strict_schema(FinalAnswer),
}

# ------------------------------------------------------------------------ facts

_ID_KEYS = re.compile(r"(^|_)(id|ids|ref)$")
_ANCHOR_KEYS = ("run_id", "comparison_id", "analysis_id", "report_id", "scenario_revision_id")


@dataclass
class NumberFact:
    value: float
    ref: str | None


@dataclass
class Facts:
    ids: dict[str, str] = field(default_factory=dict)  # id -> kind
    numbers: list[NumberFact] = field(default_factory=list)
    no_plan_runs: set[str] = field(default_factory=set)

    def add_id(self, ident: str, kind: str) -> None:
        if ident and isinstance(ident, str) and len(ident) <= 200:
            self.ids.setdefault(ident, kind)

    def add(self, obj: Any, ref: str | None = None, key: str = "") -> None:
        if isinstance(obj, dict):
            anchor = (
                next((obj[k] for k in _ANCHOR_KEYS if isinstance(obj.get(k), str)), None) or ref
            )
            if obj.get("outcome") in ("no_plan", "invalid_plan") and isinstance(
                obj.get("run_id"), str
            ):
                self.no_plan_runs.add(obj["run_id"])
            for k, v in obj.items():
                self.add(v, anchor, k)
        elif isinstance(obj, list):
            for v in obj:
                self.add(v, ref, key)
        elif isinstance(obj, bool) or obj is None:
            return
        elif isinstance(obj, int | float):
            if math.isfinite(obj):
                self.numbers.append(NumberFact(float(obj), ref))
        elif isinstance(obj, str):
            if _ID_KEYS.search(key):
                kind = key.removesuffix("_ids").removesuffix("_id").removesuffix("_ref") or "ref"
                self.add_id(obj, kind)
            elif key in ("applied_changes", "display"):
                for n in extract_numbers(obj):
                    for c in n.candidates:
                        self.numbers.append(NumberFact(c, ref))

    def add_text_numbers(self, text: str) -> None:
        for n in extract_numbers(text):
            for c in n.candidates:
                self.numbers.append(NumberFact(c, None))


# --------------------------------------------------------------- number parsing

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٬٫", "01234567890123456789,.")
UNIT_SCALE = {
    "lakh": [1e5],
    "lakhs": [1e5],
    "lac": [1e5],
    "لاکھ": [1e5],
    "crore": [1e7],
    "crores": [1e7],
    "karor": [1e7],
    "کروڑ": [1e7],
    "million": [1e6],
    "mn": [1e6],
    "ملین": [1e6],
    "m": [1e6, 1.0],
    "billion": [1e9],
    "arab": [1e9],
    "thousand": [1e3],
    "hazar": [1e3],
    "ہزار": [1e3],
    "k": [1e3],
    "t": [1e3, 1.0],
    "tonnes": [1e3, 1.0],
    "tonne": [1e3, 1.0],
    "tons": [1e3, 1.0],
    "ton": [1e3, 1.0],
    "ٹن": [1e3, 1.0],
    "%": [0.01, 1.0],
    "percent": [0.01, 1.0],
    "فیصد": [0.01, 1.0],
    "pct": [0.01, 1.0],
}
_NUM = re.compile(
    r"(?<![\w:/\-.#])(\d[\d,]*(?:\.\d+)?)"
    r"(?:(\s?%)|\s*(lakhs?|lac|crores?|karor|million|mn|billion|arab|thousand|hazar|k|m|t|tonnes?|tons?|"
    r"percent|pct|لاکھ|کروڑ|ملین|ہزار|ٹن|فیصد)(?![\w]))?"
    r"(?![\w:/\-])",
    re.UNICODE,
)


@dataclass
class WrittenNumber:
    text: str
    value: float
    candidates: list[float]
    step: float
    start: int
    end: int
    unitless_int: bool


def extract_numbers(text: str) -> list[WrittenNumber]:
    s = (text or "").translate(_DIGITS)
    out: list[WrittenNumber] = []
    for m in _NUM.finditer(s):
        raw = m.group(1).rstrip(",")
        if raw.count(",") and not re.fullmatch(r"\d{1,3}(,\d{2,3})+(\.\d+)?", raw):
            continue
        num = raw.replace(",", "")
        try:
            v = float(num)
        except ValueError:
            continue
        dec = len(num.split(".")[1]) if "." in num else 0
        unit = (m.group(2) or m.group(3) or "").strip().lower()
        scales = UNIT_SCALE.get(unit, [1.0])
        step = 10.0 ** (-dec)
        cands = [v * sc for sc in scales]
        out.append(
            WrittenNumber(m.group(0), v, cands, step, m.start(), m.end(), not unit and dec == 0)
        )
    return out


def _exempt(n: WrittenNumber) -> bool:
    # small counts, ordinals and years
    return n.unitless_int and (n.value <= 12 or 1900 <= n.value <= 2100)


def number_supported(n: WrittenNumber, facts: Facts) -> bool:
    if _exempt(n):
        return True
    for c in n.candidates:
        scale = c / n.value if n.value else 1.0
        tol_abs = 0.5 * n.step * abs(scale) * 1.0001 + 1e-9
        for f in facts.numbers:
            for fv in (f.value, abs(f.value)):
                if abs(c - fv) <= tol_abs or (fv and abs(c - fv) / abs(fv) <= 0.005):
                    return True
    return False


def unsupported_numbers(text: str, facts: Facts) -> list[str]:
    return [n.text.strip() for n in extract_numbers(text) if not number_supported(n, facts)]


def refs_for_text(text: str, facts: Facts) -> list[str]:
    """Run/comparison IDs whose numbers the text quotes (auto-citation)."""
    refs: list[str] = []
    for n in extract_numbers(text):
        if _exempt(n):
            continue
        for f in facts.numbers:
            if f.ref and any(
                abs(c - f.value)
                <= max(0.5 * n.step * (c / n.value if n.value else 1), 0.005 * abs(f.value))
                for c in n.candidates
            ):
                if f.ref not in refs:
                    refs.append(f.ref)
                break
    return refs


_SENT = re.compile(r"[^.!?۔؟\n]+[.!?۔؟]?", re.UNICODE)


def withhold_sentences(text: str, bad: list[str], language: str) -> str:
    notice = {
        "en": "[A figure here was withheld because no tool result supports it; see the cards.]",
        "ur": "[یہاں ایک عدد روک دیا گیا کیونکہ کسی ٹول نتیجے سے اس کی تصدیق نہیں ہوئی؛ کارڈ دیکھیں۔]",
        "roman_ur": "[Yahan aik figure rok diya gaya kyun ke kisi tool result se iski tasdeeq nahi hui; cards dekhein.]",
    }[language]
    out = []
    for sent in _SENT.findall(text):
        if any(b in sent.translate(_DIGITS) for b in bad):
            if not out or out[-1] != notice:
                out.append(notice)
        else:
            out.append(sent.strip())
    return " ".join(x for x in out if x)


# ------------------------------------------------------------------- validation


@dataclass
class Validation:
    blocks: list[dict[str, Any]]
    issues: list[str]
    numeric_issues: list[tuple[int, list[str]]]

    @property
    def ok(self) -> bool:
        return not self.issues and not self.numeric_issues


async def validate_answer(answer: FinalAnswer, facts: Facts, tctx: Any) -> Validation:
    """Resolve cards server-side and check references and prose numbers. ``tctx`` is a ToolCtx."""
    from aabflow.copilot.tools.backend import ToolFailure

    blocks: list[dict[str, Any]] = []
    issues: list[str] = []
    numeric: list[tuple[int, list[str]]] = []
    if answer.needs_clarification and not (answer.clarification_question or "").strip():
        issues.append("needs_clarification is true but clarification_question is empty")
    for i, b in enumerate(answer.blocks):
        if b.type in ("text", "uncertainty"):
            text = (b.text or "").strip()
            if not text:
                issues.append(f"block {i}: empty {b.type} block")
                continue
            cites = []
            for c in b.citations or []:
                if c in facts.ids:
                    cites.append({"ref_id": c, "kind": facts.ids[c]})
                else:
                    issues.append(
                        f"block {i}: citation {c!r} was not returned by any tool in this turn"
                    )
            bad = unsupported_numbers(text, facts)
            if bad:
                numeric.append((i, bad))
            for r in refs_for_text(text, facts):
                if r in facts.ids and not any(x["ref_id"] == r for x in cites):
                    cites.append({"ref_id": r, "kind": facts.ids[r], "auto": True})
            blocks.append({"type": b.type, "text": text, "citations": cites, "_origin": i})
        elif b.type == "metric":
            if not b.metric_id or not b.run_id:
                issues.append(f"block {i}: metric block needs metric_id and run_id")
                continue
            if b.run_id not in facts.ids:
                issues.append(f"block {i}: run {b.run_id} was not returned by a tool in this turn")
                continue
            if b.run_id in facts.no_plan_runs:
                issues.append(
                    f"block {i}: run {b.run_id} has no plan, so it has no {b.metric_id}; use an "
                    "uncertainty block instead"
                )
                continue
            try:
                view = await tctx.run_in_pilot(b.run_id)
            except ToolFailure as exc:
                issues.append(f"block {i}: {exc.detail}")
                continue
            m = next(
                (
                    m
                    for m in view.get("metrics", [])
                    if m["metric_id"] == b.metric_id and m.get("field_id") == b.field_id
                ),
                None,
            )
            if m is None:
                issues.append(
                    f"block {i}: metric {b.metric_id} (field {b.field_id}) does not exist in run {b.run_id}"
                )
                continue
            from aabflow.copilot.tools.base import metric_basis

            blocks.append(
                {
                    "type": "metric",
                    "metric_id": m["metric_id"],
                    "definition_id": m["definition_id"],
                    "run_id": b.run_id,
                    "field_id": m.get("field_id"),
                    "value": m.get("value"),
                    "unit": m.get("unit"),
                    "status": m.get("status"),
                    "reason": m.get("reason"),
                    "basis": metric_basis(m["metric_id"]),
                    "plan_kind": view["run"]["plan_kind"],
                    "solver_status": view["run"]["solver_status"],
                }
            )
        elif b.type == "comparison":
            if not b.comparison_id or b.comparison_id not in facts.ids:
                issues.append(
                    f"block {i}: comparison {b.comparison_id!r} was not created by compare_runs this turn"
                )
                continue
            try:
                cmp = await tctx.backend.get(f"/comparisons/{b.comparison_id}")
            except ToolFailure as exc:
                issues.append(f"block {i}: {exc.detail}")
                continue
            blocks.append(
                {
                    "type": "comparison",
                    "comparison_id": b.comparison_id,
                    "run_ids": cmp["run_ids"],
                    "compatible": cmp["compatible"],
                    "label": cmp["labels"]["comparison"],
                    "deltas": [
                        {k: d[k] for k in ("metric_id", "unit", "a", "b", "delta", "status")}
                        for d in cmp["deltas"]
                        if d["field_id"] is None
                    ],
                    "fields_worse_off": cmp.get("fields_worse_off", []),
                }
            )
        elif b.type == "action":
            if not b.action or not b.ref_id:
                issues.append(f"block {i}: action block needs action and ref_id")
                continue
            if b.ref_id not in facts.ids:
                issues.append(f"block {i}: {b.ref_id!r} was not returned by a tool in this turn")
                continue
            blocks.append(
                {
                    "type": "action",
                    "action": b.action,
                    "ref_id": b.ref_id,
                    "label": (b.label or b.action.replace("_", " "))[:80],
                }
            )
    if not blocks and not answer.needs_clarification:
        issues.append("the answer has no valid blocks")
    return Validation(blocks, issues, numeric)


def apply_fallback(v: Validation, language: str) -> list[dict[str, Any]]:
    """Replace unsupported numeric sentences with a withheld notice (after one failed regeneration)."""
    bad = dict(v.numeric_issues)
    out = []
    for b in v.blocks:
        b = dict(b)
        if b.get("_origin") in bad:
            b["text"] = withhold_sentences(b["text"], bad[b["_origin"]], language)
            b["withheld"] = True
        out.append(b)
    return out


def public_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in b.items() if not k.startswith("_")} for b in blocks]
