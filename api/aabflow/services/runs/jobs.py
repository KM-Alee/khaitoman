"""Solve job handler: executes one B0/B1/P/R run in a worker process."""

from __future__ import annotations

from aabflow.domain.schemas import PlanKind
from aabflow.services.runs import RunContext, SolveOptions, execute


def solve_job(ctx, payload: dict) -> str:
    rc = RunContext.from_settings(ctx.settings)
    opts = SolveOptions(
        plan_kind=PlanKind(payload.get("plan_kind", "P")),
        time_limit_s=float(payload.get("time_limit_s", 10.0)),
        workers=int(payload.get("solver_workers", ctx.settings.solver_workers)),
        seed=int(payload.get("seed", 0)),
        job_id=ctx.job_id,
    )
    ctx.stage(
        "started",
        {
            "plan_kind": opts.plan_kind.value,
            "scenario_revision_id": payload["scenario_revision_id"],
        },
    )
    run_id = execute(
        rc,
        ctx.conn,
        payload["scenario_revision_id"],
        opts,
        token=ctx.token,
        progress=lambda stage: ctx.stage(stage),
    )
    return run_id
