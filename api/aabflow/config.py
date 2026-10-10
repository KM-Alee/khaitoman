"""Runtime configuration read from the environment (.env is loaded by main).

Module constants keep their original names for other streams. The API builds a
``Settings`` object at app creation so tests can point every store at a
temporary directory (and at labelled fixture bindings) without touching ``data/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_VERSION = "2.0.0"
DATA_DIR = Path(os.environ.get("AABFLOW_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("AABFLOW_DB_PATH", DATA_DIR / "app.sqlite"))
WEB_DIST = ROOT / "web" / "dist"
OPENAI_MODEL = os.environ.get("AABFLOW_OPENAI_MODEL", "gpt-6.1-sol")

# Production science bindings (library loading, ledger reconstruction, trajectories).
DEFAULT_SCIENCE_BINDINGS = "aabflow.services.science:bindings"


def openai_key_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    web_dist: Path = WEB_DIST
    workers: int = 2
    solver_workers: int = 2
    science_bindings: str = DEFAULT_SCIENCE_BINDINGS
    start_dispatcher: bool = True
    heartbeat_s: float = 2.0
    lease_s: float = 15.0
    extra: dict = field(default_factory=dict)
    cors_origins: tuple[str, ...] = ()

    @property
    def pilots_dir(self) -> Path:
        return self.data_dir / "pilots"

    @property
    def libraries_dir(self) -> Path:
        return self.data_dir / "libraries"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def onboarding_dir(self) -> Path:
        return self.data_dir / "onboarding"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    def with_(self, **kw) -> Settings:
        return replace(self, **kw)


def settings_from_env() -> Settings:
    data = Path(os.environ.get("AABFLOW_DATA_DIR", ROOT / "data"))
    return Settings(
        data_dir=data,
        db_path=Path(os.environ.get("AABFLOW_DB_PATH", data / "app.sqlite")),
        workers=int(os.environ.get("AABFLOW_WORKERS", "2")),
        solver_workers=int(os.environ.get("AABFLOW_SOLVER_WORKERS", "2")),
        cors_origins=parse_cors_origins(os.environ.get("AABFLOW_CORS_ORIGINS", "")),
    )


def parse_cors_origins(raw: str) -> tuple[str, ...]:
    """Explicit browser origins only; never grant credentialed access to a wildcard."""
    origins = tuple(dict.fromkeys(s.strip().rstrip("/") for s in raw.split(",") if s.strip()))
    for origin in origins:
        url = urlsplit(origin)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
            or "*" in origin
        ):
            raise ValueError("AABFLOW_CORS_ORIGINS must contain explicit http(s) origins")
    return origins
