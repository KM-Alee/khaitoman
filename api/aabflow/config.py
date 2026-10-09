"""Runtime configuration read from the environment (.env is loaded by main)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_VERSION = "2.0.0"
DATA_DIR = Path(os.environ.get("AABFLOW_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("AABFLOW_DB_PATH", DATA_DIR / "app.sqlite"))
WEB_DIST = ROOT / "web" / "dist"
OPENAI_MODEL = os.environ.get("AABFLOW_OPENAI_MODEL", "gpt-6.1-sol")


def openai_key_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))
