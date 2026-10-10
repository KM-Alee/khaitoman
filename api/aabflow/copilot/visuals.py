"""Chat visual contract: server-materialized datasets and the visual blocks built from them.

Tools register *datasets* (typed columns with units and provenance, rows copied from
authoritative service results) in the turn's :class:`DatasetStore`. The model never
types chart numbers: in ``final_answer`` it picks a ``dataset_id``, a chart kind and
which columns to encode (:class:`VisualSpec`). The server validates the spec against
the dataset and builds the :class:`VisualBlock` the UI renders, copying values from
the stored rows. Every visual therefore carries the run/analysis/comparison IDs,
units and basis labels of the tool result it came from (AT13).

The UI contract (public models below) is exported through OpenAPI and documented in
``docs/COPILOT.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aabflow.copilot.registry import ToolArgs

ChartKind = Literal[
    "kpi",  # metric cards (one card per row)
    "table",
    "bar",
    "grouped_bar",
    "stacked_bar",
    "delta_bar",  # diverging bars of server-computed differences
    "line",
    "area",
    "scatter",
    "frontier",  # scatter of solved settings; nondominated points joined
    "heatmap",  # e.g. the weather x supply stress matrix
    "sankey",  # water ledger flows
    "map",  # field highlight / choropleth on the workspace map
    "steps",  # dated action cards
]
CHART_KINDS: tuple[str, ...] = ChartKind.__args__  # type: ignore[attr-defined]

ColumnKind = Literal["category", "number", "id", "date", "text", "bool", "status"]
Basis = Literal[
    "model_output",
    "computed_from_inputs",
    "assumption",
    "observed",
    "surrogate_preview",
    "solver_result",
]
RefKind = Literal["run", "field", "analysis", "instance", "comparison", "revision", "report"]

MAX_VISUAL_ROWS = 400
MAX_VISUALS = 4


class _Public(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Column(_Public):
    key: str
    label: str
    label_ur: str | None = None
    kind: ColumnKind = "number"
    unit: str | None = Field(
        None, description="Unit of every value in this column (kg, PKR, m3, ratio, ...)"
    )
    unit_column: str | None = Field(
        None,
        description="For mixed-unit columns (metric cards): the column holding each row's unit",
    )
    basis: Basis | None = None
    ref: RefKind | None = Field(
        None, description="ID column kind: selecting a row opens this entity in the workspace"
    )


class Encoding(_Public):
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    series: str | None = None
    value: str | None = None
    label: str | None = None
    color: str | None = None
    source: str | None = None
    target: str | None = None
    id: str | None = None
    status: str | None = None


class DatasetSource(_Public):
    tool: str
    call_id: str | None = None
    run_ids: list[str] = Field(default_factory=list)
    analysis_ids: list[str] = Field(default_factory=list)
    comparison_ids: list[str] = Field(default_factory=list)
    revision_ids: list[str] = Field(default_factory=list)
    endpoint: str | None = Field(None, description="The /api/v2 resource the rows were copied from")


class Interaction(_Public):
    on: Literal["select_row", "select_point", "select_cell", "select_field"]
    column: str
    intent: Literal["open_run", "open_field", "open_analysis", "open_comparison", "open_branch"]


class VisualBlock(_Public):
    """A chart/table/map block whose values were copied from a server dataset."""

    type: Literal["visual"] = "visual"
    visual_id: str
    chart: ChartKind
    title: str
    caption: str | None = None
    dataset_id: str
    dataset_kind: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False
    encoding: Encoding
    highlight_ids: list[str] = Field(default_factory=list)
    source: DatasetSource
    basis: list[Basis] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    interactions: list[Interaction] = Field(default_factory=list)
    table_fallback: bool = Field(
        True, description="Always true: the UI must offer the rows as an accessible table"
    )
    auto: bool = Field(False, description="Added by the server (no model explanation available)")


# ------------------------------------------------------------- model-facing spec


class VisualSpec(ToolArgs):
    """What the model may choose for a visual: never values, only which dataset and columns."""

    dataset_id: str = Field(description="dataset_id returned by a tool in this turn, e.g. ds2")
    chart: ChartKind = Field(description="One of the dataset's suggested charts")
    title: str = Field(description="Short plain-language title in the answer language")
    caption: str | None = Field(
        None, description="One sentence telling a lay reader what to look at; no new numbers"
    )
    x: str | None = Field(None, description="Column key for the x axis/category; null = default")
    y: list[str] | None = Field(None, description="Numeric column keys to plot; null = default")
    series: str | None = Field(None, description="Column key that splits series; null = default")
    sort: Literal["asc", "desc"] | None = Field(None, description="Sort rows by the first y column")
    limit: int | None = Field(None, description="Keep only the first N rows after sorting")
    highlight_ids: list[str] | None = Field(
        None, description="Row IDs (field/run IDs from the dataset) to emphasise"
    )


# ---------------------------------------------------------------- dataset store


@dataclass
class Dataset:
    dataset_id: str
    kind: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    charts: list[str]
    defaults: dict[str, Encoding]
    source: DatasetSource
    basis: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def col(self, key: str | None) -> Column | None:
        return next((c for c in self.columns if c.key == key), None)

    def descriptor(self, max_inline_rows: int = 12) -> dict[str, Any]:
        """Compact description returned to the model inside the tool output.

        Small datasets also carry their rows so the model can read the values it talks about."""
        out = {
            "dataset_id": self.dataset_id,
            "title": self.title,
            "kind": self.kind,
            "rows": len(self.rows),
            "columns": [
                [c.key, c.label, c.unit or (f"per-row:{c.unit_column}" if c.unit_column else None)]
                for c in self.columns
            ],
            "charts": self.charts,
        }
        if len(self.rows) <= max_inline_rows:
            out["data"] = self.rows
        return out


class DatasetStore:
    """Per-turn registry of materialized datasets (``ds1``, ``ds2`` ...)."""

    def __init__(self) -> None:
        self.items: dict[str, Dataset] = {}
        self._n = 0
        self.on_add: Any = None  # callback(dataset) for streaming "dataset_ready" events

    def add(
        self,
        *,
        kind: str,
        title: str,
        columns: list[Column],
        rows: list[dict[str, Any]],
        charts: list[str],
        source: DatasetSource,
        defaults: dict[str, Encoding] | None = None,
        basis: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> Dataset:
        keys = {c.key for c in columns}
        clean = [{k: _clean(v) for k, v in r.items() if k in keys} for r in rows]
        for ch in charts:
            if ch not in CHART_KINDS:
                raise ValueError(f"unknown chart kind {ch}")
        self._n += 1
        ds = Dataset(
            dataset_id=f"ds{self._n}",
            kind=kind,
            title=title,
            columns=columns,
            rows=clean,
            charts=list(dict.fromkeys(["table", *charts])),
            defaults=defaults or {},
            source=source,
            basis=sorted(set(basis or [])),
            notes=list(notes or []),
        )
        self.items[ds.dataset_id] = ds
        if self.on_add is not None:
            self.on_add(ds)
        return ds

    def get(self, dataset_id: str) -> Dataset | None:
        return self.items.get(dataset_id)


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return float(f"{v:.6g}") if abs(v) < 1e15 else v
    return v


# --------------------------------------------------------------- materialization

_NUMERIC = ("number",)
_CATEGORICAL = ("category", "id", "date", "text", "status", "bool")


@dataclass
class Materialized:
    block: VisualBlock | None
    issues: list[str]


def _need(
    ds: Dataset, key: str | None, kinds: tuple[str, ...], role: str, issues: list[str]
) -> None:
    c = ds.col(key)
    if c is None:
        issues.append(f"{ds.dataset_id}: {role} column {key!r} does not exist")
    elif c.kind not in kinds:
        issues.append(
            f"{ds.dataset_id}: {role} column {key!r} is {c.kind}, needs {'/'.join(kinds)}"
        )


def materialize(spec: VisualSpec, store: DatasetStore, visual_id: str) -> Materialized:
    """Validate a model's visual choice and copy the authoritative rows into a block."""
    issues: list[str] = []
    ds = store.get(spec.dataset_id)
    if ds is None:
        return Materialized(
            None, [f"visual: dataset {spec.dataset_id!r} was not returned by a tool this turn"]
        )
    if spec.chart not in ds.charts:
        return Materialized(
            None, [f"visual: {spec.dataset_id} supports {ds.charts}, not {spec.chart!r}"]
        )
    d = ds.defaults.get(spec.chart) or ds.defaults.get("*") or Encoding()
    enc = d.model_copy(deep=True)
    if spec.x is not None:
        enc.x = spec.x
    if spec.y:
        ys = list(dict.fromkeys(spec.y))
        yc = ds.col(ys[0]) if len(ys) == 1 else None
        if spec.chart in ("heatmap", "map") and yc is not None and yc.kind == "number":
            enc.value = ys[0]  # "y" naming the measured value means the cell/field colour
        else:
            enc.y = ys
    if spec.series is not None:
        enc.series = spec.series
    ch = spec.chart
    if ch in ("bar", "grouped_bar", "stacked_bar", "delta_bar", "line", "area"):
        _need(ds, enc.x, _CATEGORICAL + _NUMERIC, "x", issues)
        if not enc.y:
            issues.append(f"{ds.dataset_id}: {ch} needs at least one y column")
        for y in enc.y:
            _need(ds, y, _NUMERIC, "y", issues)
        if enc.series:
            _need(ds, enc.series, _CATEGORICAL, "series", issues)
    elif ch in ("scatter", "frontier"):
        _need(ds, enc.x, _NUMERIC, "x", issues)
        if len(enc.y) != 1:
            issues.append(f"{ds.dataset_id}: {ch} needs exactly one y column")
        for y in enc.y:
            _need(ds, y, _NUMERIC, "y", issues)
    elif ch == "heatmap":
        _need(ds, enc.x, _CATEGORICAL, "x", issues)
        if len(enc.y) != 1:
            issues.append(f"{ds.dataset_id}: heatmap needs exactly one y (row category) column")
        for y in enc.y:
            _need(ds, y, _CATEGORICAL, "y", issues)
        _need(ds, enc.value, _NUMERIC, "value", issues)
    elif ch == "sankey":
        _need(ds, enc.source, _CATEGORICAL, "source", issues)
        _need(ds, enc.target, _CATEGORICAL, "target", issues)
        _need(ds, enc.value, _NUMERIC, "value", issues)
    elif ch == "map":
        c = ds.col(enc.id)
        if c is None or c.ref != "field":
            issues.append(f"{ds.dataset_id}: map needs a field ID column")
        if enc.value is None and enc.color is None:
            issues.append(f"{ds.dataset_id}: map needs a value or color column")
    elif ch in ("kpi", "steps"):
        if enc.label is None or ds.col(enc.label) is None:
            issues.append(f"{ds.dataset_id}: {ch} has no label column")
    elif ch == "table":
        if spec.y:
            for y in spec.y:
                if ds.col(y) is None:
                    issues.append(f"{ds.dataset_id}: table column {y!r} does not exist")
    if issues:
        return Materialized(None, issues)

    rows = [dict(r) for r in ds.rows]
    sort_key = (enc.y[0] if enc.y else None) or enc.value
    if spec.sort and sort_key:
        present = [r for r in rows if isinstance(r.get(sort_key), int | float)]
        missing = [r for r in rows if not isinstance(r.get(sort_key), int | float)]
        present.sort(key=lambda r: r[sort_key], reverse=spec.sort == "desc")
        rows = present + missing  # gaps stay visible at the end, never as zeros
    if spec.limit is not None and spec.limit > 0:
        rows = rows[: spec.limit]
    truncated = len(rows) > MAX_VISUAL_ROWS
    rows = rows[:MAX_VISUAL_ROWS]

    if ch == "table" and spec.y:
        keep = set(spec.y) | {c.key for c in ds.columns if c.ref or c.kind in ("id",)}
        if enc.x:
            keep.add(enc.x)
        cols = [c for c in ds.columns if c.key in keep]
        unit_cols = {c.unit_column for c in cols if c.unit_column}
        cols += [c for c in ds.columns if c.key in unit_cols and c not in cols]
        rows = [{k: r.get(k) for k in (c.key for c in cols)} for r in rows]
    else:
        cols = list(ds.columns)

    id_cols = {c.key for c in ds.columns if c.ref}
    valid_ids = {str(r.get(k)) for r in ds.rows for k in id_cols if r.get(k) is not None}
    highlight = [h for h in (spec.highlight_ids or []) if h in valid_ids]
    dropped = [h for h in (spec.highlight_ids or []) if h not in valid_ids]
    notes = list(ds.notes)
    if dropped:
        notes.append(f"{len(dropped)} highlight ID(s) not in this dataset were ignored")

    interactions: list[Interaction] = []
    for c in cols:
        if c.ref == "run":
            interactions.append(
                Interaction(
                    on="select_point"
                    if ch in ("scatter", "frontier")
                    else "select_cell"
                    if ch == "heatmap"
                    else "select_row",
                    column=c.key,
                    intent="open_run",
                )
            )
        elif c.ref == "field":
            interactions.append(
                Interaction(
                    on="select_field" if ch == "map" else "select_row",
                    column=c.key,
                    intent="open_field",
                )
            )
        elif c.ref == "analysis":
            interactions.append(Interaction(on="select_row", column=c.key, intent="open_analysis"))
    block = VisualBlock(
        visual_id=visual_id,
        chart=ch,
        title=(spec.title or ds.title).strip()[:140],
        caption=(spec.caption or "").strip()[:400] or None,
        dataset_id=ds.dataset_id,
        dataset_kind=ds.kind,
        columns=cols,
        rows=rows,
        row_count=len(ds.rows),
        truncated=truncated or len(rows) < len(ds.rows),
        encoding=enc,
        highlight_ids=highlight,
        source=ds.source,
        basis=ds.basis,  # type: ignore[arg-type]
        notes=notes,
        interactions=interactions,
    )
    return Materialized(block, [])


def default_visual(ds: Dataset, visual_id: str) -> VisualBlock | None:
    """Server-chosen visual for a dataset (used only when the model could not finish)."""
    chart = next((c for c in ds.charts if c != "table"), "table")
    spec = VisualSpec(
        dataset_id=ds.dataset_id,
        chart=chart,  # type: ignore[arg-type]
        title=ds.title,
        caption=None,
        x=None,
        y=None,
        series=None,
        sort=None,
        limit=None,
        highlight_ids=None,
    )
    m = materialize(spec, _single(ds), visual_id)
    if m.block is None:
        return None
    m.block.auto = True
    return m.block


def _single(ds: Dataset) -> DatasetStore:
    s = DatasetStore()
    s.items[ds.dataset_id] = ds
    return s
