"""Science-owned artifact locations under ``data/`` (STREAMS.md)."""

from __future__ import annotations

import os
from pathlib import Path

from aabflow.config import DATA_DIR


def data_dir() -> Path:
    return DATA_DIR


def experiments_dir() -> Path:
    return DATA_DIR / "experiments"


def libraries_dir() -> Path:
    return DATA_DIR / "libraries"


def weather_store_dir() -> Path:
    """Normalized and scenario-transformed weather, addressed by content sha256."""
    return DATA_DIR / "libraries" / "weather"


def pilots_dir() -> Path:
    return DATA_DIR / "pilots"


def models_dir() -> Path:
    return DATA_DIR / "models"


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file + rename so readers never see partial artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
