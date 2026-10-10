"""Surrogate evaluation metrics and decision-regret fixtures (T8.3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

GATES = {
    "nmae_max": 0.10,
    "median_spearman_min": 0.90,
    "median_regret_max": 0.03,
    "max_regret_max": 0.10,
    "min_decision_fixtures": 10,
}


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def regression_metrics(y: np.ndarray, yhat: np.ndarray, reference_kg_ha: float) -> dict[str, float]:
    err = yhat - y
    mae = float(np.mean(np.abs(err)))
    return {
        "n": len(y),
        "mae_kg_ha": mae,
        "rmse_kg_ha": float(np.sqrt(np.mean(err**2))),
        "bias_kg_ha": float(np.mean(err)),
        "nmae": mae / reference_kg_ha,
        "reference_yield_kg_ha": reference_kg_ha,
    }


def within_context_spearman(
    df: pd.DataFrame, pred_col: str, context_cols: list[str]
) -> dict[str, float | int]:
    vals = []
    for _, g in df.groupby(context_cols):
        r = spearman(g["yield_kg_ha"].to_numpy(), g[pred_col].to_numpy())
        if r is not None:
            vals.append(r)
    return {
        "contexts": len(vals),
        "median_spearman": float(np.median(vals)) if vals else float("nan"),
        "min_spearman": float(np.min(vals)) if vals else float("nan"),
    }


def _knapsack(options: list[list[tuple[int, float]]], cap: int) -> list[int]:
    """Exactly one option per field, total water units <= cap, maximise value. Returns choice idx."""
    n = len(options)
    neg = -1e18
    best = np.full(cap + 1, neg)
    best[0] = 0.0
    choice = []
    for opts in options:
        nb = np.full(cap + 1, neg)
        ch = np.full(cap + 1, -1, dtype=int)
        for j, (w, v) in enumerate(opts):
            if w > cap:
                continue
            cand = np.full(cap + 1, neg)
            cand[w:] = best[: cap + 1 - w] + v
            upd = cand > nb
            nb[upd] = cand[upd]
            ch[upd] = j
        best = nb
        choice.append(ch)
    c = int(np.argmax(best))
    if best[c] <= neg / 2:
        raise ValueError("no feasible portfolio")
    picks = [0] * n
    for i in range(n - 1, -1, -1):
        j = int(choice[i][c])
        picks[i] = j
        c -= options[i][j][0]
    return picks


@dataclass
class RegretFixture:
    fixture_id: str
    fields: list[dict]  # soil, eff, area_ha
    water_cap_m3: float
    description: str


def decision_regret(
    test: pd.DataFrame, pred_col: str, n_fixtures: int = 12, seed: int = 7, unit_m3: float = 10.0
) -> list[dict]:
    """Portfolio fixtures inside the held-out year: vary soils, efficiency, areas, water budget/shortage.

    Each field picks one exactly simulated schedule; the surrogate's choice is
    scored by *exact* production; regret = (exact optimum - exact of surrogate choice) / exact optimum.
    """
    rng = np.random.default_rng(seed)
    contexts = sorted({(s, e) for s, e in zip(test["soil"], test["app_eff"], strict=True)})
    out = []
    budgets = [0.35, 0.5, 0.65, 0.8]
    shortages = [1.0, 0.78]
    for k in range(n_fixtures):
        nf = 6
        picks = [contexts[i] for i in rng.integers(0, len(contexts), nf)]
        areas = rng.uniform(1.0, 3.0, nf).round(2)
        options = []
        for (soil, eff), area in zip(picks, areas, strict=True):
            g = test[(test["soil"] == soil) & (test["app_eff"] == eff)]
            options.append(
                [
                    (
                        int(np.ceil(r.irr_total_mm * area * 10 / unit_m3)),
                        float(r.yield_kg_ha) * area,
                        float(getattr(r, pred_col)) * area,
                    )
                    for r in g.itertuples()
                ]
            )
        max_w = sum(max(o[0] for o in opts) for opts in options)
        frac = budgets[k % len(budgets)] * shortages[(k // len(budgets)) % len(shortages)]
        cap = int(max_w * frac)
        exact_pick = _knapsack([[(w, v) for w, v, _ in opts] for opts in options], cap)
        sur_pick = _knapsack([[(w, p) for w, _, p in opts] for opts in options], cap)
        exact_opt = sum(options[i][j][1] for i, j in enumerate(exact_pick))
        attained = sum(options[i][j][1] for i, j in enumerate(sur_pick))
        out.append(
            {
                "fixture_id": f"regret-{k:02d}",
                "fields": [
                    {"soil": s, "app_eff": e, "area_ha": float(a)}
                    for (s, e), a in zip(picks, areas, strict=True)
                ],
                "water_cap_m3": cap * unit_m3,
                "budget_fraction": budgets[k % len(budgets)],
                "shortage_multiplier": shortages[(k // len(budgets)) % len(shortages)],
                "exact_optimum_kg": exact_opt,
                "surrogate_choice_exact_kg": attained,
                "regret_kg": exact_opt - attained,
                "regret": (exact_opt - attained) / exact_opt if exact_opt > 0 else 0.0,
            }
        )
    return out


def gate(metrics: dict) -> dict[str, bool]:
    t = metrics["test"]
    reg = [f["regret"] for f in metrics["decision_regret"]]
    return {
        "nmae": t["nmae"] <= GATES["nmae_max"],
        "median_spearman": metrics["test_ranking"]["median_spearman"]
        >= GATES["median_spearman_min"],
        "median_regret": float(np.median(reg)) <= GATES["median_regret_max"],
        "max_regret": float(np.max(reg)) <= GATES["max_regret_max"],
        "fixtures": len(reg) >= GATES["min_decision_fixtures"],
        "beats_naive_baseline": t["mae_kg_ha"] < metrics["baseline_test"]["mae_kg_ha"],
    }
