"""Server-owned turn context (T11.1).

The UI sends what it is showing; the server resolves it against published pilots,
runs and revisions and pins the result for the whole turn. Tools read only the
pinned context and re-check membership, so the model cannot retarget a workspace
by inserting another ID. A selection that does not belong to the selected pilot
(for example a run left over from a previously selected pilot) is dropped with a
visible note rather than silently used.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aabflow.copilot.tools.backend import Backend, ToolFailure

Language = Literal["en", "ur", "roman_ur"]


class UIContext(BaseModel):
    """What the client says it is showing when the user sends a message."""

    model_config = ConfigDict(extra="forbid")

    pilot_id: str | None = None
    pilot_version: str | None = None
    season_id: str | None = None
    scenario_revision_id: str | None = None
    selected_run_id: str | None = None
    selected_field_id: str | None = None
    timeline_date: date | None = None
    view: str | None = None  # workspace | compare | explore | impact | onboarding | copilot
    language: Language = "en"
    units: Literal["metric"] = "metric"
    ui_revision: int | None = None


class PinnedContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pilot_id: str
    pilot_version: str
    pilot_name: str
    season_id: str | None = None
    crop: str | None = None
    scenario_id: str | None = None
    scenario_revision_id: str | None = None
    selected_run_id: str | None = None
    selected_run_plan_kind: str | None = None
    selected_run_outcome: str | None = None
    selected_field_id: str | None = None
    timeline_date: date | None = None
    view: str | None = None
    language: Language = "en"
    units: str = "metric"
    role: Literal["planner", "viewer"] = "planner"
    ui_revision: int | None = None
    permitted_pilots: list[dict[str, str]] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    pinned_at: datetime

    def prompt_view(self) -> dict[str, Any]:
        """Compact JSON for the system prompt (no capabilities dump)."""
        d = self.model_dump(mode="json", exclude={"capabilities", "permitted_pilots", "pinned_at"})
        d["permitted_pilot_ids"] = [p["pilot_id"] for p in self.permitted_pilots]
        d["unavailable_features"] = sorted(
            k
            for k, v in (self.capabilities.get("features") or {}).items()
            if v.get("status") == "not_available"
        )
        return {k: v for k, v in d.items() if v not in (None, [], {})}


async def resolve(backend: Backend, ui: UIContext, *, role: str = "planner") -> PinnedContext:
    """Resolve a client context into a pinned, membership-checked context."""
    pilots = (await backend.get("/pilots"))["pilots"]
    if not pilots:
        raise ToolFailure("ASSET_UNAVAILABLE", "no published pilot package")
    permitted = [
        {"pilot_id": p["pilot_id"], "pilot_version": p["pilot_version"], "name": p["name"]}
        for p in pilots
    ]
    notes: list[str] = []
    chosen = next((p for p in pilots if p["pilot_id"] == ui.pilot_id), None)
    if chosen is None:
        if ui.pilot_id:
            notes.append(
                f"requested pilot {ui.pilot_id!r} is not published; using {pilots[0]['pilot_id']}"
            )
        chosen = pilots[0]
    pilot_id = chosen["pilot_id"]
    version = (
        ui.pilot_version
        if ui.pilot_version in chosen.get("versions", [])
        else chosen["pilot_version"]
    )
    if ui.pilot_version and ui.pilot_version != version:
        notes.append(f"pilot version {ui.pilot_version!r} is not published; using {version}")
    caps = await backend.get("/capabilities")

    season_id = ui.season_id
    revision_id = ui.scenario_revision_id
    scenario_id = None
    run_id = ui.selected_run_id
    run_kind = run_outcome = None

    if run_id:
        try:
            run = await backend.get(f"/runs/{run_id}")
            meta = run.get("meta") or {}
            if meta.get("pilot_id") != pilot_id or meta.get("pilot_version") != version:
                notes.append(
                    f"selected run {run_id} belongs to {meta.get('pilot_id')}/{meta.get('pilot_version')}, "
                    f"not the selected pilot; it is not used"
                )
                run_id = None
            else:
                run_kind = run["run"]["plan_kind"]
                run_outcome = run["run"]["solver_status"]
                season_id = season_id or meta.get("season_id")
                revision_id = revision_id or run["run"]["scenario_revision_id"]
        except ToolFailure:
            notes.append(f"selected run {run_id} was not found; it is not used")
            run_id = None
    if revision_id:
        try:
            rv = await backend.get(f"/scenario-revisions/{revision_id}")
            req = rv["revision"]["request"]
            if req["pilot_id"] != pilot_id:
                notes.append(
                    f"scenario revision {revision_id} belongs to another pilot; it is not used"
                )
                revision_id = None
            else:
                scenario_id = rv["revision"]["scenario_id"]
                season_id = season_id or req["season_id"]
        except ToolFailure:
            notes.append(f"scenario revision {revision_id} was not found; it is not used")
            revision_id = None
    field_id = ui.selected_field_id
    if field_id:
        try:
            fd = await backend.get(f"/fields/{field_id}", pilot_id=pilot_id, pilot_version=version)
            if fd["pilot_id"] != pilot_id:
                raise ToolFailure("NOT_FOUND", "other pilot")
        except ToolFailure:
            notes.append(f"selected field {field_id} is not in {pilot_id}; it is not used")
            field_id = None
    crop = None
    if season_id:
        seasons = (await backend.get("/seasons", pilot_id=pilot_id))["seasons"]
        match = next((s for s in seasons if s["season"]["season_id"] == season_id), None)
        if match is None:
            notes.append(f"season {season_id!r} is not configured for {pilot_id}; it is not used")
            season_id = None
        else:
            crop = match["season"].get("crop") or match["season"].get("crop_profile_id")
    return PinnedContext(
        pilot_id=pilot_id,
        pilot_version=version,
        pilot_name=chosen["name"],
        season_id=season_id,
        crop=crop,
        scenario_id=scenario_id,
        scenario_revision_id=revision_id,
        selected_run_id=run_id,
        selected_run_plan_kind=run_kind,
        selected_run_outcome=run_outcome,
        selected_field_id=field_id,
        timeline_date=ui.timeline_date,
        view=ui.view,
        language=ui.language,
        units=ui.units,
        role=role,  # type: ignore[arg-type]
        ui_revision=ui.ui_revision,
        permitted_pilots=permitted,
        capabilities=caps,
        notes=notes,
        pinned_at=datetime.now(UTC),
    )


# ------------------------------------------------------------- per-turn digest

_ROMAN_URDU = {
    "kya",
    "kia",
    "hai",
    "hain",
    "agar",
    "kitna",
    "kitni",
    "kitne",
    "nahi",
    "nahin",
    "mein",
    "kyun",
    "kyon",
    "batao",
    "bataen",
    "bataiye",
    "paani",
    "pani",
    "nehar",
    "nahar",
    "fasal",
    "kisan",
    "zameen",
    "behtar",
    "kaisa",
    "kaise",
    "karo",
    "karen",
    "hoga",
    "hogi",
    "wala",
    "wali",
}


def detect_language(message: str, default: str = "en") -> tuple[str, str | None]:
    """Language of the user's message: Urdu script, Roman Urdu (word heuristic) or the UI default."""
    text = message or ""
    arabic = sum(1 for ch in text if "؀" <= ch <= "ۿ")
    letters = sum(1 for ch in text if ch.isalpha())
    if letters and arabic / letters > 0.3:
        return "ur", "The user wrote in Urdu script: answer in Urdu (language ur)."
    words = {w.strip("?.,!;:'\"").lower() for w in text.split()}
    hits = len(words & _ROMAN_URDU)
    if hits >= 2 and hits / max(1, len(words)) >= 0.15:
        return (
            "roman_ur",
            "The user appears to write Roman Urdu: answer in Roman Urdu (language roman_ur).",
        )
    return default, None


async def workspace_digest(backend: Backend, ctx: PinnedContext) -> dict[str, Any]:
    """Compact, authoritative overview for the system prompt so the model can pick tools in round one.

    Everything comes from the same routes the UI uses; a failed lookup leaves its key out.
    """
    out: dict[str, Any] = {}
    if ctx.scenario_revision_id:
        try:
            rv = await backend.get(f"/scenario-revisions/{ctx.scenario_revision_id}")
            req = rv["revision"]["request"]
            out["scenario"] = {
                k: req.get(k)
                for k in (
                    "planning_mode",
                    "capital_budget_pkr",
                    "operating_budget_pkr",
                    "supply_profile_id",
                    "uniform_reduction_fraction",
                    "weather_scenario_ids",
                    "minimum_service_ratio",
                    "service_group",
                    "uncertainty_set_id",
                )
            }
            latest: dict[str, Any] = {}
            for r in rv.get("runs", []):
                if not r.get("analysis_id"):
                    latest[r["plan_kind"]] = {
                        "run_id": r["run_id"],
                        "solver_status": r["solver_status"],
                    }
            out["plans_in_scenario"] = latest
        except ToolFailure:
            pass
        try:
            an = await backend.get("/analyses", base_revision_id=ctx.scenario_revision_id, limit=20)
            items = list(an.get("analyses", []))
            if ctx.selected_run_id:
                more = await backend.get("/analyses", base_run_id=ctx.selected_run_id, limit=20)
                seen = {x["analysis_id"] for x in items}
                items += [a for a in more.get("analyses", []) if a["analysis_id"] not in seen]
            out["saved_analyses"] = [
                {
                    "analysis_id": a["analysis_id"],
                    "kind": a["kind"],
                    "mode": (a.get("request") or {}).get("mode"),
                    "base_run_id": a.get("base_run_id"),
                }
                for a in items
                if a.get("status") == "completed"
            ][:10]
        except ToolFailure:
            pass
    if ctx.season_id:
        try:
            us = await backend.get(
                "/uncertainty-sets", pilot_id=ctx.pilot_id, season_id=ctx.season_id
            )
            states = [s for u in us.get("uncertainty_sets", []) for s in u.get("states", [])]
            out["supply_profiles"] = sorted({s["supply_profile_id"] for s in states})
            out["weather_scenarios"] = sorted({s["weather_scenario_id"] for s in states})
        except ToolFailure:
            pass
    try:
        pm = await backend.get(f"/pilots/{ctx.pilot_id}/versions/{ctx.pilot_version}/map")
        groups: dict[str, int] = {}
        for g in (pm.get("field_groups") or {}).values():
            groups[g] = groups.get(g, 0) + 1
        out["fields_by_canal_position"] = groups
    except ToolFailure:
        pass
    return out
