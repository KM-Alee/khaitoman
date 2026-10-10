"""TEST FIXTURE helpers: build an AabFlow app over a temporary data directory."""

from __future__ import annotations

from pathlib import Path

from aabflow.config import Settings

FIXTURE_BINDINGS = "tests.fixtures.synthetic_science:bindings"


def settings_for(
    tmp: Path, *, dispatcher: bool = False, bindings: str = FIXTURE_BINDINGS, workers: int = 2
) -> Settings:
    return Settings(
        data_dir=Path(tmp),
        db_path=Path(tmp) / "app.sqlite",
        web_dist=Path(tmp) / "no-web-dist",
        start_dispatcher=dispatcher,
        science_bindings=bindings,
        workers=workers,
        solver_workers=1,
        heartbeat_s=0.5,
        lease_s=5.0,
    )
