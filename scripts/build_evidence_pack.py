"""Proof package (PRD §13.3, review plan P08): assemble existing evidence into one folder.

Writes ``evidence/pack/<UTC ts>/`` with

* copies of real artifacts that may be redistributed (pilot packages and raw bundles whose
  licences are known to permit it, Delineate run records/outputs, candidate library
  manifests, surrogate evaluations, completed run bundles, app-database records, frontend
  check outputs, command logs, benchmarks, chat evaluation transcripts, rehearsal recording),
* hash references for files that are too large or not redistributable (policy dumps,
  model weights, oversized rasters/GeoJSON, anything under an unknown licence),
* ``manifest.json``: every file's pack path, size, sha256 and source path,
* ``capability-report.json`` / ``capability-report.md``: each F01–F20 and AT01–AT18 with the
  status recorded in ``docs/STATUS.md`` and every artifact path cited there, checked for
  existence.

Nothing is generated, retrained or re-run. Missing proof items are listed as missing.
Text artifacts are scanned for credential patterns and redacted; ``.env`` files are never
read. AT17 is never reported passed (user decision 2026-10-10: the 30x3 copilot
evaluation is not run).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK_VERSION = "1"
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024
EXPERIMENT_SAMPLES_PER_CROP = 2

FEATURE_IDS = tuple(f"F{n:02d}" for n in range(1, 21))
AT_IDS = tuple(f"AT{n:02d}" for n in range(1, 19))
NEVER_PASSED = {
    "AT17": "AT17 is never reported passed: the 30x3 copilot evaluation was not run "
    "(user decision 2026-10-10)."
}
REPORT_STATUSES = ("passed", "failed", "blocked", "not_run")

# Licence identifiers whose terms permit redistribution with attribution/share-alike.
REDISTRIBUTABLE_LICENCES = (
    "CC-BY-4.0",
    "CC0-1.0",
    "ODbL-1.0",
    "PDDL-1.0",
    "copernicus-sentinel-data-terms",
    "copernicus-dem-glo30-licence",
    "AGPL-3.0 (Delineate Anything code)",
)

TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".geojson",
    ".md",
    ".log",
    ".txt",
    ".yaml",
    ".yml",
    ".csv",
    ".html",
    ".xml",
    ".toml",
    ".ini",
    ".py",
    ".ts",
    ".js",
}
SKIP_NAMES = {".gitkeep", ".DS_Store"}
SKIP_SUFFIXES = (".aux.xml",)

# Credential patterns. Strong patterns are also checked in binary files.
STRONG_SECRET_PATTERNS = {
    "openai_or_anthropic_key": r"sk-(?:ant-|proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}",
    "github_token": r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "google_api_key": r"AIza[0-9A-Za-z_\-]{35}",
    "slack_token": r"xox[abposr]-[A-Za-z0-9\-]{10,}",
}
ASSIGNMENT_SECRET = re.compile(
    r"(?i)(\b\w*(?:api[_-]?key|secret|token|password|passwd|access[_-]?key)\w*[\"']?\s*[:=]\s*"
    r"[\"']?)([A-Za-z0-9_\-\.+/=]{16,})"
)
BEARER_SECRET = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9_\-\.=]{20,})")
REDACTED = "[REDACTED]"

PATH_ROOTS = (
    "api",
    "contracts",
    "data",
    "docker",
    "docs",
    "evidence",
    "review",
    "scripts",
    "tests",
    "vision",
    "web",
)


# ---------------------------------------------------------------- helpers


def utc_stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_env_file(path: Path) -> bool:
    return path.name == ".env" or path.name.startswith(".env.")


def licence_permits(licence: str | None) -> bool:
    return licence in REDISTRIBUTABLE_LICENCES


def scrub_text(text: str) -> tuple[str, int]:
    """Redact credential-like values. Returns the new text and the redaction count."""
    count = 0
    for pattern in STRONG_SECRET_PATTERNS.values():
        text, n = re.subn(pattern, REDACTED, text)
        count += n

    def keep_prefix(match: re.Match[str]) -> str:
        nonlocal count
        if match.group(2) == REDACTED.strip("[]"):
            return match.group(0)
        count += 1
        return match.group(1) + REDACTED

    text = ASSIGNMENT_SECRET.sub(keep_prefix, text)
    text = BEARER_SECRET.sub(keep_prefix, text)
    return text, count


def binary_has_secret(data: bytes) -> bool:
    return any(re.search(p.encode(), data) for p in STRONG_SECRET_PATTERNS.values())


def iter_files(base: Path) -> Iterable[Path]:
    if not base.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in {"node_modules", ".git"})
        for name in sorted(filenames):
            yield Path(dirpath) / name


def skipped(path: Path) -> bool:
    return (
        path.name in SKIP_NAMES
        or path.name.endswith(SKIP_SUFFIXES)
        or is_env_file(path)
        or path.suffix == ".pyc"
    )


# ---------------------------------------------------------------- pack builder


@dataclass
class Item:
    item_id: str
    title: str
    searched: list[str]
    notes: list[str] = field(default_factory=list)
    copied: int = 0
    referenced: int = 0
    generated: int = 0
    bytes_copied: int = 0

    def summary(self) -> dict:
        found = (self.copied + self.referenced + self.generated) > 0
        return {
            "id": self.item_id,
            "title": self.title,
            "status": "found" if found else "missing",
            "files_copied": self.copied,
            "files_referenced": self.referenced,
            "files_generated": self.generated,
            "bytes_copied": self.bytes_copied,
            "searched": self.searched,
            "notes": self.notes,
        }


ITEMS = (
    ("pilot_sources", "Versioned pilot sources permitted for redistribution"),
    ("raw_inference", "Raw inference evidence (Delineate Anything runs)"),
    ("scientific_outputs", "Scientific outputs (exact AquaCrop experiments)"),
    ("candidate_manifests", "Candidate library manifests, density and adequacy"),
    ("model_evaluation", "Model evaluation (surrogate) and model references"),
    ("completed_runs", "Completed run IDs with original-precision ledgers and solver bounds"),
    ("analyses", "Frontier/stress/synergy analyses linked to run records"),
    ("reports", "Generated decision reports"),
    ("frontend_checks", "Frontend check outputs (Playwright, screenshots)"),
    ("command_logs", "Command and environment logs"),
    ("benchmarks", "Benchmarks"),
    ("chat_eval_transcripts", "Chat evaluation transcripts (secrets removed)"),
    ("rehearsal", "Rehearsal recording"),
    ("other_evidence", "Other evidence folders"),
    ("capability_report", "Capability report (F01-F20, AT01-AT18)"),
)


class PackBuilder:
    def __init__(self, root: Path, pack_dir: Path, max_file_bytes: int):
        self.root = root.resolve()
        self.pack = pack_dir
        self.max_file_bytes = max_file_bytes
        self.files: list[dict] = []
        self.items = {iid: Item(iid, title, []) for iid, title in ITEMS}
        self.delineate_keys: dict[str, list[str]] = {}
        self.claimed: set[Path] = set()
        self.redacted_files = 0
        self.redactions = 0
        self.withheld_for_secrets: list[str] = []

    # ---- bookkeeping

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def search(self, item: str, *patterns: str) -> None:
        self.items[item].searched.extend(patterns)

    def note(self, item: str, text: str) -> None:
        self.items[item].notes.append(text)

    def copy(self, item: str, src: Path, dest: str, *, licence: str | None = None) -> None:
        """Copy one file (or reference it when oversize/unsafe). ``dest`` is pack-relative."""
        src_resolved = src.resolve()
        if src_resolved in self.claimed or skipped(src) or not src.is_file():
            return
        self.claimed.add(src_resolved)
        size = src.stat().st_size
        if size > self.max_file_bytes:
            self.reference(
                item,
                src,
                f"larger than the {self.max_file_bytes} byte pack threshold",
                licence=licence,
            )
            return
        data = src.read_bytes()
        entry = {
            "path": dest,
            "source": self.rel(src),
            "item": item,
            "mode": "copied",
            "licence": licence,
        }
        out = self.pack / dest
        out.parent.mkdir(parents=True, exist_ok=True)
        text = None
        if src.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
        if text is not None:
            new, n = scrub_text(text)
            if n:
                entry["source_sha256"] = sha256_bytes(data)
                entry["redactions"] = n
                self.redacted_files += 1
                self.redactions += n
                data = new.encode("utf-8")
        elif binary_has_secret(data):
            self.claimed.discard(src_resolved)
            self.withheld_for_secrets.append(self.rel(src))
            self.reference(item, src, "withheld: binary contains a credential-like pattern")
            return
        out.write_bytes(data)
        entry["size_bytes"] = len(data)
        entry["sha256"] = sha256_bytes(data)
        self.files.append(entry)
        self.items[item].copied += 1
        self.items[item].bytes_copied += len(data)

    def reference(self, item: str, src: Path, reason: str, *, licence: str | None = None) -> None:
        self.claimed.add(src.resolve())
        self.files.append(
            {
                "path": None,
                "source": self.rel(src),
                "item": item,
                "mode": "referenced",
                "reason": reason,
                "licence": licence,
                "size_bytes": src.stat().st_size,
                "sha256": sha256_file(src),
            }
        )
        self.items[item].referenced += 1

    def write_generated(
        self, item: str, dest: str, data: bytes, source: str, *, counts: bool = True
    ) -> None:
        """Write a pack-made file. ``counts=False`` keeps an empty export from marking the
        item found (an empty ``reports`` table is not a report)."""
        out = self.pack / dest
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        self.files.append(
            {
                "path": dest,
                "source": source,
                "item": item,
                "mode": "generated",
                "size_bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
        if counts:
            self.items[item].generated += 1

    def copy_tree(self, item: str, base: Path, dest_prefix: str, **kw) -> int:
        n = 0
        for f in iter_files(base):
            if f.resolve() in self.claimed or skipped(f):
                continue
            self.copy(item, f, f"{dest_prefix}/{f.relative_to(base).as_posix()}", **kw)
            n += 1
        return n

    # ---- collectors

    def pilots(self) -> None:
        item = "pilot_sources"
        pilots_dir = self.root / "data" / "pilots"
        self.search(item, "data/pilots/index.json", "data/pilots/<id>/<version>/manifest.json")
        index_path = pilots_dir / "index.json"
        if not index_path.is_file():
            self.note(item, "data/pilots/index.json not found")
            return
        self.copy(item, index_path, "pilots/index.json")
        bundle_ids: set[str] = set()
        for entry in json.loads(index_path.read_text()):
            pid, ver = entry["pilot_id"], entry["pilot_version"]
            pkg = pilots_dir / pid / ver
            manifest_path = pkg / "manifest.json"
            if not manifest_path.is_file():
                self.note(item, f"{pid}/{ver}: manifest.json missing")
                continue
            manifest = json.loads(manifest_path.read_text())
            licences = list(manifest.get("licenses") or [])
            blocked = [lic for lic in licences if not licence_permits(lic)]
            self.copy(item, manifest_path, f"pilots/{pid}/{ver}/manifest.json")
            for sid in manifest.get("source_ids", []):
                if sid.startswith("bundle:"):
                    bundle_ids.add(sid.removeprefix("bundle:"))
                if sid.startswith("delineate:"):
                    key = sid.removeprefix("delineate:")
                    self.delineate_keys.setdefault(key, []).append(f"{pid}/{ver}")
            bad_hash = []
            for f in manifest.get("files", []):
                src = pkg / f["path"]
                if not src.is_file():
                    self.note(item, f"{pid}/{ver}: listed file missing: {f['path']}")
                    continue
                if f.get("sha256") and sha256_file(src) != f["sha256"]:
                    bad_hash.append(f["path"])
                if blocked:
                    self.reference(
                        item, src, f"package licence not known to permit redistribution: {blocked}"
                    )
                else:
                    self.copy(
                        item, src, f"pilots/{pid}/{ver}/{f['path']}", licence="; ".join(licences)
                    )
            if bad_hash:
                self.note(item, f"{pid}/{ver}: sha256 differs from manifest for {bad_hash}")
            else:
                self.note(item, f"{pid}/{ver}: every listed file matches its manifest sha256")
            if blocked:
                self.note(item, f"{pid}/{ver}: referenced only, licences {blocked} not allowlisted")
            else:
                self.note(item, f"{pid}/{ver}: licences {licences} permit redistribution")
        for extra in sorted(pilots_dir.glob("*/*.json")) + sorted(
            pilots_dir.glob("review_edits/*.json")
        ):
            self.copy(item, extra, f"pilots/{extra.relative_to(pilots_dir).as_posix()}")
        intake = pilots_dir / ".intake"
        for f in (
            sorted(intake.glob("*/intake.json"))
            + sorted(intake.glob("*/processed/process_result.json"))
            + sorted(intake.glob("*/review/*.json"))
        ):
            self.copy(item, f, f"pilots/intake/{f.relative_to(intake).as_posix()}")
        self.search(item, "data/raw/bundles/<pilot>/<bundle>/bundle_manifest.json")
        for bid in sorted(bundle_ids):
            bdir = self.root / "data" / "raw" / "bundles" / bid
            bman = bdir / "bundle_manifest.json"
            if not bman.is_file():
                self.note(item, f"raw bundle {bid} cited by a pilot manifest is missing")
                continue
            self.copy(item, bman, f"raw-bundles/{bid}/bundle_manifest.json")
            for f in json.loads(bman.read_text()).get("files", []):
                src = bdir / f["path"]
                if not src.is_file():
                    self.note(item, f"raw bundle {bid}: listed file missing: {f['path']}")
                    continue
                lic = f.get("license_id")
                if lic is None or licence_permits(lic):
                    self.copy(item, src, f"raw-bundles/{bid}/{f['path']}", licence=lic)
                else:
                    self.reference(item, src, f"licence {lic!r} not known to permit redistribution")
            self.note(
                item,
                f"raw bundle {bid}: files with license_id null are project-generated request/"
                "metadata records; licensed source files are copied only when allowlisted",
            )

    def inference(self) -> None:
        item = "raw_inference"
        keys = self.delineate_keys
        runs = self.root / "vision" / "runs"
        self.search(
            item,
            "vision/runs/<key>/",
            "vision/batches/",
            "vision/configs/",
            "evidence/benchmarks/delineate-*",
        )
        for key, users in sorted(keys.items()):
            if not (runs / key / "run.json").is_file():
                self.note(item, f"delineate:{key} cited by {users} has no run record")
            else:
                self.note(item, f"delineate:{key} cited by {users}: run record present")
        for run in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []:
            self.copy_tree(item, run, f"inference/vision-runs/{run.name}")
        self.copy_tree(item, self.root / "vision" / "batches", "inference/batches")
        self.copy_tree(item, self.root / "vision" / "configs", "inference/configs")
        for f in sorted((self.root / "evidence" / "benchmarks").glob("delineate-*")):
            self.copy(item, f, f"evidence/benchmarks/{f.name}")
        sums = self.root / "data" / "models" / "delineate-anything" / "SHA256SUMS"
        self.copy(item, sums, "inference/weights/SHA256SUMS")
        for w in sorted(sums.parent.glob("*.pt")):
            self.reference(item, w, "third-party model weights; not redistributed in the pack")

    def science(self) -> None:
        item = "scientific_outputs"
        exp_dir = self.root / "data" / "experiments"
        self.search(
            item,
            "data/experiments/<experiment_hash>/",
            "evidence/benchmarks/science-*",
            "evidence/benchmarks/crop-bench-*",
        )
        lines: list[str] = []
        samples: dict[str, list[Path]] = {}
        total_bytes = 0
        if exp_dir.is_dir():
            for d in sorted(p for p in exp_dir.iterdir() if p.is_dir()):
                files = [f for f in d.iterdir() if f.is_file()]
                size = sum(f.stat().st_size for f in files)
                total_bytes += size
                rec: dict = {"experiment_hash": d.name, "files": len(files), "bytes": size}
                meta = d / "experiment.json"
                if meta.is_file():
                    try:
                        exp = json.loads(meta.read_text())
                    except json.JSONDecodeError:
                        exp = {}
                    for k in (
                        "crop_profile_id",
                        "soil_profile_id",
                        "weather_scenario_id",
                        "engine_version",
                    ):
                        rec[k] = exp.get(k)
                    crop = exp.get("crop_profile_id") or "unknown"
                    if len(samples.setdefault(crop, [])) < EXPERIMENT_SAMPLES_PER_CROP:
                        samples[crop].append(d)
                lines.append(json.dumps(rec, sort_keys=True))
        if lines:
            self.write_generated(
                item,
                "science/experiments-index.jsonl",
                ("\n".join(lines) + "\n").encode(),
                "data/experiments",
            )
            self.note(
                item,
                f"{len(lines)} exact experiment directories ({total_bytes} bytes) are referenced by "
                "index; each directory name is its experiment content hash",
            )
            for crop, dirs in sorted(samples.items()):
                for d in dirs:
                    self.copy_tree(item, d, f"science/experiments-sample/{d.name}")
                self.note(
                    item,
                    f"copied {len(dirs)} complete {crop} experiment(s) (first by hash order) as an "
                    "inspectable sample of raw AquaCrop outputs",
                )
        else:
            self.note(item, "data/experiments has no experiment directories")
        bench = self.root / "evidence" / "benchmarks"
        for pattern in ("science-*", "crop-bench-*", "p01-completion-*", "p01-reproducibility-*"):
            for f in sorted(bench.glob(pattern)):
                if f.is_file():
                    self.copy(item, f, f"evidence/benchmarks/{f.name}")

    def libraries(self) -> None:
        item = "candidate_manifests"
        lib = self.root / "data" / "libraries"
        self.search(
            item,
            "data/libraries/**/{library,latest,density,adequacy}.json",
            "data/libraries/*.json",
        )
        for f in sorted(lib.glob("*.json")):
            self.copy(item, f, f"libraries/{f.name}")
        for name in ("latest.json", "density.json", "adequacy.json"):
            for f in sorted(lib.glob(f"*/*/{name}")):
                self.copy(item, f, f"libraries/{f.relative_to(lib).as_posix()}")
        for f in sorted(lib.glob("*/*/*/library.json")):
            self.copy(item, f, f"libraries/{f.relative_to(lib).as_posix()}")
        for f in sorted(lib.glob("*/*/*/policies.jsonl")):
            self.reference(
                item, f, "policy dump regenerated by `make candidates`; hash pinned here"
            )
        weather = lib / "weather"
        if weather.is_dir():
            n = sum(1 for _ in weather.glob("*.parquet"))
            self.note(
                item,
                f"data/libraries/weather holds {n} content-addressed weather parquet files (not copied)",
            )

    def models(self) -> None:
        item = "model_evaluation"
        models = self.root / "data" / "models"
        self.search(
            item,
            "data/models/surrogate-latest.json",
            "data/models/surrogate-*/",
            "evidence/surrogate-*",
        )
        latest_path = models / "surrogate-latest.json"
        latest = None
        if latest_path.is_file():
            self.copy(item, latest_path, "models/surrogate-latest.json")
            latest = json.loads(latest_path.read_text()).get("model_version")
        for d in sorted(models.glob("surrogate-*")):
            if not d.is_dir():
                continue
            if d.name == latest:
                self.copy_tree(item, d, f"models/{d.name}")
                self.note(item, f"{d.name} is the released pointer; complete directory included")
            else:
                for f in sorted(d.glob("*.json")):
                    self.copy(item, f, f"models/{d.name}/{f.name}")
        for d in sorted((self.root / "evidence").glob("surrogate-*")):
            self.copy_tree(item, d, f"evidence/{d.name}")
        bench = self.root / "evidence" / "benchmarks"
        for pattern in ("p01-gpu-*", "p04-preview-*"):
            for f in sorted(bench.glob(pattern)):
                self.copy(item, f, f"evidence/benchmarks/{f.name}")
        self.copy_tree(
            item, bench / "p01-model-development", "evidence/benchmarks/p01-model-development"
        )

    def database(self) -> dict[str, list[dict]]:
        """Read the app DB once as a consistent snapshot. Never writes the source DB."""
        db = self.root / "data" / "app.sqlite"
        if not db.is_file():
            return {}
        conn: sqlite3.Connection | None = None
        snapshot = sqlite3.connect(":memory:")
        try:
            conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
            conn.backup(snapshot)
        except sqlite3.Error:
            # Read-only mount without -shm: read a private copy of db + wal instead.
            with tempfile.TemporaryDirectory() as tmp:
                for suffix in ("", "-wal"):
                    if Path(f"{db}{suffix}").is_file():
                        shutil.copy2(f"{db}{suffix}", Path(tmp) / f"app.sqlite{suffix}")
                copy = sqlite3.connect(Path(tmp) / "app.sqlite")
                copy.backup(snapshot)
                copy.close()
        finally:
            if conn is not None:
                conn.close()
        snapshot.row_factory = sqlite3.Row
        tables = [
            r[0]
            for r in snapshot.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        out: dict[str, list[dict]] = {}
        for t in tables:
            if t.startswith(("evidence_fts", "sqlite_")) or t == "idempotency":
                continue
            out[t] = [dict(r) for r in snapshot.execute(f'SELECT * FROM "{t}"')]
        snapshot.close()
        return out

    def run_path(self, raw: str, run_id: str) -> Path:
        p = Path(raw)
        if p.is_absolute() and p.parts[:2] == ("/", "app"):
            p = self.root.joinpath(*p.parts[2:])
        elif not p.is_absolute():
            p = self.root / p
        if not p.is_dir():
            p = self.root / "data" / "runs" / run_id
        return p

    def runs_and_db(self) -> list[dict]:
        tables = self.database()
        self.search("completed_runs", "data/app.sqlite (runs)", "data/runs/<run_id>/")
        self.search("analyses", "data/app.sqlite (analyses)", "evidence/benchmarks/analyses-*")
        self.search("reports", "data/app.sqlite (reports)", "data/reports/<report_id>/")
        self.search("chat_eval_transcripts", "evidence/copilot/", "data/app.sqlite (copilot_turns)")
        if not tables:
            self.note("completed_runs", "data/app.sqlite not found")
        for name, rows in sorted(tables.items()):
            if name.startswith("copilot_"):
                continue
            item = {"runs": "completed_runs", "analyses": "analyses", "reports": "reports"}.get(
                name, "completed_runs"
            )
            text, n = scrub_text(json.dumps(rows, indent=1, sort_keys=True, default=str))
            self.redactions += n
            self.redacted_files += 1 if n else 0
            self.write_generated(
                item,
                f"app-db/{name}.json",
                text.encode(),
                f"data/app.sqlite#{name}",
                counts=bool(rows) and name in ("runs", "analyses", "reports"),
            )
        turns = tables.get("copilot_turns", [])
        if turns:
            payload = {
                "label": "copilot session transcripts from the app DB; not the 30x3 evaluation",
                "sessions": tables.get("copilot_sessions", []),
                "turns": turns,
                "tool_calls": tables.get("copilot_tool_calls", []),
            }
            text, n = scrub_text(json.dumps(payload, indent=1, sort_keys=True, default=str))
            self.redactions += n
            self.redacted_files += 1 if n else 0
            self.write_generated(
                "chat_eval_transcripts",
                "chat/copilot-transcripts.json",
                text.encode(),
                "data/app.sqlite#copilot_*",
            )
        runs_summary = []
        registered: set[Path] = set()
        for row in tables.get("runs", []):
            run_id = row["run_id"]
            rdir = self.run_path(row["run_dir"], run_id)
            registered.add(rdir.resolve())
            check = verify_run_manifest(rdir)
            runs_summary.append(
                {
                    "run_id": run_id,
                    "plan_kind": row.get("plan_kind"),
                    "outcome": row.get("outcome"),
                    "solver_status": row.get("solver_status"),
                    "analysis_id": row.get("analysis_id"),
                    "candidate_library_hash": row.get("candidate_library_hash"),
                    "manifest_sha256": row.get("manifest_sha256"),
                    "manifest_check": check,
                    "has_ledger": (rdir / "ledger.parquet").is_file(),
                    "has_solver_log": (rdir / "solver.json").is_file(),
                }
            )
            if rdir.is_dir():
                self.copy_tree("completed_runs", rdir, f"runs/{run_id}")
        runs_dir = self.root / "data" / "runs"
        orphans = [
            d
            for d in sorted(runs_dir.glob("run_*"))
            if d.is_dir() and d.resolve() not in registered
        ]
        for d in orphans:
            self.note(
                "completed_runs",
                f"{d.name} exists on disk but has no runs-table record; not copied",
            )
        bad = [r["run_id"] for r in runs_summary if r["manifest_check"] != "verified"]
        self.note(
            "completed_runs",
            f"{len(runs_summary)} run records; {len(runs_summary) - len(bad)} bundles match their "
            f"manifest.json hashes" + (f"; not verified: {bad}" if bad else ""),
        )
        analyses = tables.get("analyses", [])
        if analyses:
            kinds: dict[str, int] = {}
            for a in analyses:
                kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
            self.note("analyses", f"analyses table: {kinds}")
        for f in sorted((self.root / "evidence" / "benchmarks").glob("analyses-*")):
            self.copy("analyses", f, f"evidence/benchmarks/{f.name}")
        report_rows = tables.get("reports", [])
        for row in report_rows:
            rdir = row.get("report_dir")
            if rdir:
                p = self.run_path(rdir, row["report_id"])
                if not p.is_dir():
                    p = self.root / "data" / "reports" / row["report_id"]
                self.copy_tree("reports", p, f"reports/{row['report_id']}")
        for d in sorted((self.root / "data" / "reports").glob("*")):
            if d.is_dir():
                self.copy_tree("reports", d, f"reports/{d.name}")
        return runs_summary

    def evidence_dirs(self) -> None:
        ev = self.root / "evidence"
        web = self.root / "web"
        self.search(
            "frontend_checks",
            "web/test-results/",
            "web/playwright-report/",
            "evidence/screenshots/",
            "evidence/playwright-output/",
        )
        self.copy_tree("frontend_checks", web / "test-results", "frontend/web-test-results")
        self.copy_tree("frontend_checks", web / "playwright-report", "frontend/playwright-report")
        self.copy_tree("frontend_checks", ev / "screenshots", "evidence/screenshots")
        self.copy_tree("frontend_checks", ev / "playwright-output", "evidence/playwright-output")
        self.search("command_logs", "evidence/commands/", "evidence/environment/")
        self.copy_tree("command_logs", ev / "commands", "evidence/commands")
        self.copy_tree("command_logs", ev / "environment", "evidence/environment")
        self.search("benchmarks", "evidence/benchmarks/")
        self.copy_tree("benchmarks", ev / "benchmarks", "evidence/benchmarks")
        self.copy_tree("chat_eval_transcripts", ev / "copilot", "evidence/copilot")
        self.search("rehearsal", "evidence/rehearsal/")
        self.copy_tree("rehearsal", ev / "rehearsal", "evidence/rehearsal")
        self.search("other_evidence", "evidence/<other>/")
        known = {
            "commands",
            "environment",
            "benchmarks",
            "screenshots",
            "playwright-output",
            "copilot",
            "rehearsal",
            "pack",
        }
        for d in sorted(p for p in ev.iterdir() if p.is_dir()) if ev.is_dir() else []:
            if d.name not in known:
                self.copy_tree("other_evidence", d, f"evidence/{d.name}")


def verify_run_manifest(run_dir: Path) -> str:
    manifest = run_dir / "manifest.json"
    if not run_dir.is_dir():
        return "missing_dir"
    if not manifest.is_file():
        return "missing_manifest"
    try:
        files = json.loads(manifest.read_text()).get("files", [])
    except json.JSONDecodeError:
        return "invalid_manifest"
    for f in files:
        p = run_dir / f["path"]
        if not p.is_file():
            return "missing_file"
        if p.stat().st_size != f.get("size_bytes") or sha256_file(p) != f.get("sha256"):
            return "hash_mismatch"
    return "verified"


# ---------------------------------------------------------------- capability report

_BACKTICK = re.compile(r"`([^`\s]+)`")
_TEST_NAME = re.compile(r"^test_\w+$")


def parse_status(text: str) -> dict[str, dict]:
    """Rows of the Features and Acceptance tests tables in docs/STATUS.md."""
    rows: dict[str, dict] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        rid = cells[0]
        if rid in FEATURE_IDS or rid in AT_IDS:
            rows[rid] = {
                "title": cells[1],
                "milestone": cells[2],
                "status_md": cells[3],
                "evidence": "|".join(cells[4:]).strip(),
            }
    return rows


def find_test(root: Path, name: str) -> str | None:
    needle = f"def {name}("
    for f in iter_files(root / "tests"):
        if f.suffix == ".py" and needle in f.read_text(errors="ignore"):
            return f"{f.relative_to(root).as_posix()}::{name}"
    return None


def cited_paths(root: Path, evidence: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for raw in _BACKTICK.findall(evidence):
        token = raw.rstrip(".,;:")
        if _TEST_NAME.match(token):
            found = find_test(root, token)
            ref = {
                "cited": token,
                "kind": "test",
                "exists": found is not None,
                "resolved": [found] if found else [],
            }
        else:
            path = token.split("::", 1)[0]
            first = path.split("/", 1)[0]
            if "/" not in path or first not in PATH_ROOTS:
                continue
            if any(ch in path for ch in "*?["):
                matches = sorted(p.relative_to(root).as_posix() for p in root.glob(path))
                ref = {"cited": token, "kind": "glob", "exists": bool(matches), "resolved": matches}
            else:
                exists = (root / path).exists()
                ref = {
                    "cited": token,
                    "kind": "path",
                    "exists": exists,
                    "resolved": [path] if exists else [],
                }
        if ref["cited"] not in seen:
            seen.add(ref["cited"])
            out.append(ref)
    return out


def report_status(rid: str, status_md: str | None) -> tuple[str, str | None]:
    s = (status_md or "").strip().lower()
    status = s if s in ("passed", "failed", "blocked") else "not_run"
    note = None
    if rid in NEVER_PASSED and status == "passed":
        status, note = "not_run", NEVER_PASSED[rid]
    elif rid in NEVER_PASSED:
        note = NEVER_PASSED[rid]
    return status, note


def capability_report(root: Path, pack_sources: dict[str, str], generated_at: str) -> dict:
    status_path = root / "docs" / "STATUS.md"
    rows = parse_status(status_path.read_text()) if status_path.is_file() else {}
    entries = []
    for rid in FEATURE_IDS + AT_IDS:
        row = rows.get(rid)
        status, note = report_status(rid, row["status_md"] if row else None)
        refs = cited_paths(root, row["evidence"]) if row else []
        for ref in refs:
            ref["in_pack"] = [pack_sources[r] for r in ref["resolved"] if r in pack_sources]
        warnings = [f"cited path does not exist: {r['cited']}" for r in refs if not r["exists"]]
        if row is None:
            warnings.append("row missing from docs/STATUS.md")
        if status == "passed" and not any(r["exists"] for r in refs) and not row["evidence"]:
            warnings.append("passed without any recorded evidence")
        entries.append(
            {
                "id": rid,
                "kind": "feature" if rid.startswith("F") else "acceptance_test",
                "title": row["title"] if row else None,
                "milestone": row["milestone"] if row else None,
                "status": status,
                "status_md": row["status_md"] if row else None,
                "note": note,
                "evidence_text": row["evidence"] if row else None,
                "artifact_refs": refs,
                "warnings": warnings,
            }
        )
    counts = {s: sum(1 for e in entries if e["status"] == s) for s in REPORT_STATUSES}
    return {
        "generated_at": generated_at,
        "source": "docs/STATUS.md",
        "status_values": list(REPORT_STATUSES),
        "full_release_complete": all(e["status"] == "passed" for e in entries),
        "counts": counts,
        "entries": entries,
    }


def render_report_md(report: dict, items: list[dict], secret_scan: dict) -> str:
    lines = [
        "# AabFlow capability report",
        "",
        (
            f"Generated {report['generated_at']} from `docs/STATUS.md`. Status values: passed, "
            "failed, blocked, not_run. `not_run` covers rows STATUS.md records as not_started or "
            "in_progress."
        ),
        "",
        f"Full release complete: **{'yes' if report['full_release_complete'] else 'no'}**. "
        + ", ".join(f"{k}: {v}" for k, v in report["counts"].items())
        + ".",
        "",
        (
            "Field calibration and customer validation evidence are absent; software completion "
            "is not agronomic or commercial validation."
        ),
        "",
    ]
    for kind, heading in (("feature", "Features"), ("acceptance_test", "Acceptance tests")):
        lines += [
            f"## {heading}",
            "",
            "| ID | Title | Status | STATUS.md | Artifacts | Warnings and notes |",
            "|---|---|---|---|---|---|",
        ]
        for e in report["entries"]:
            if e["kind"] != kind:
                continue
            arts = (
                "<br>".join(
                    f"`{r['cited']}` ({'exists' if r['exists'] else 'MISSING'})"
                    for r in e["artifact_refs"]
                )
                or "none cited"
            )
            warn = "<br>".join(e["warnings"] + ([e["note"]] if e["note"] else [])) or ""
            title, status_md = e["title"] or "", e["status_md"] or ""
            lines.append(f"| {e['id']} | {title} | {e['status']} | {status_md} | {arts} | {warn} |")
        lines.append("")
    lines += [
        "## Proof package (PRD §13.3)",
        "",
        "| Item | Status | Copied | Referenced | Generated | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for it in items:
        if it["id"] == "other_evidence" and it["status"] == "missing":
            continue
        notes = "<br>".join(it["notes"]) or ("searched: " + ", ".join(it["searched"]))
        lines.append(
            f"| {it['title']} | {it['status']} | {it['files_copied']} | {it['files_referenced']} | "
            f"{it['files_generated']} | {notes} |"
        )
    lines += [
        "",
        "## Secret scan",
        "",
        (
            f"Patterns: {', '.join(secret_scan['patterns'])}. Files redacted: "
            f"{secret_scan['files_redacted']}; redactions: {secret_scan['redactions']}; binaries "
            f"withheld: {len(secret_scan['withheld'])}. `.env` files are never read."
        ),
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- entry point


def git_info(root: Path) -> dict:
    def run(*args: str) -> str | None:
        try:
            res = subprocess.run(
                ["git", "-c", "safe.directory=*", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return res.stdout.strip() if res.returncode == 0 else None

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": None if status is None else bool(status),
    }


def build(
    root: Path,
    out_root: Path,
    *,
    now: datetime | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> Path:
    now = now or datetime.now(UTC)
    stamp = utc_stamp(now)
    final = out_root / stamp
    if final.exists():
        raise FileExistsError(f"{final} already exists")
    out_root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{stamp}-", dir=out_root))
    try:
        b = PackBuilder(root, tmp, max_file_bytes)
        b.pilots()
        b.inference()
        b.models()
        b.science()
        b.libraries()
        runs = b.runs_and_db()
        b.evidence_dirs()
        if (
            b.items["chat_eval_transcripts"].copied + b.items["chat_eval_transcripts"].generated
            == 0
        ):
            b.note(
                "chat_eval_transcripts",
                "no chat evaluation transcripts exist (evidence/copilot/ absent and no copilot "
                "turns in the app DB); the 30x3 evaluation was not run",
            )
        if b.items["reports"].copied + b.items["reports"].generated == 0:
            b.note("reports", "no generated reports (empty reports table, no data/reports/<id>/)")
        if b.items["rehearsal"].copied + b.items["rehearsal"].referenced == 0:
            b.note("rehearsal", "no rehearsal recording exists under evidence/rehearsal/")
        generated_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
        pack_sources = {f["source"]: f["path"] for f in b.files if f["mode"] == "copied"}
        report = capability_report(b.root, pack_sources, generated_at)
        items = [it.summary() for k, it in b.items.items() if k != "capability_report"]
        secret_scan = {
            "patterns": [
                *STRONG_SECRET_PATTERNS,
                "key/secret/token/password assignment",
                "bearer token",
            ],
            "files_redacted": b.redacted_files,
            "redactions": b.redactions,
            "withheld": b.withheld_for_secrets,
        }
        b.write_generated(
            "capability_report",
            "capability-report.json",
            json.dumps(report, indent=1, sort_keys=True).encode(),
            "docs/STATUS.md",
        )
        b.write_generated(
            "capability_report",
            "capability-report.md",
            render_report_md(report, items, secret_scan).encode(),
            "docs/STATUS.md",
        )
        items = [it.summary() for it in b.items.values()]
        copied = [f for f in b.files if f["mode"] != "referenced"]
        manifest = {
            "pack_version": PACK_VERSION,
            "generated_at": generated_at,
            "pack_id": stamp,
            "git": git_info(b.root),
            "max_file_bytes": max_file_bytes,
            "licence_allowlist": list(REDISTRIBUTABLE_LICENCES),
            "totals": {
                "files_in_pack": len(copied) + 1,
                "bytes_in_pack_excluding_manifest": sum(f["size_bytes"] for f in copied),
                "files_referenced": len(b.files) - len(copied),
                "bytes_referenced": sum(
                    f["size_bytes"] for f in b.files if f["mode"] == "referenced"
                ),
            },
            "items": items,
            "missing_items": [
                it["id"]
                for it in items
                if it["status"] == "missing" and it["id"] != "other_evidence"
            ],
            "capability_counts": report["counts"],
            "full_release_complete": report["full_release_complete"],
            "secret_scan": secret_scan,
            "runs": runs,
            "files": b.files,
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
        tmp.rename(final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root to read")
    ap.add_argument(
        "--out", type=Path, default=None, help="pack parent (default <root>/evidence/pack)"
    )
    ap.add_argument("--max-file-mb", type=float, default=DEFAULT_MAX_FILE_BYTES / (1024 * 1024))
    args = ap.parse_args(argv)
    out = args.out or args.root / "evidence" / "pack"
    pack = build(args.root, out, max_file_bytes=int(args.max_file_mb * 1024 * 1024))
    manifest = json.loads((pack / "manifest.json").read_text())
    t = manifest["totals"]
    print(f"evidence pack: {pack}")
    print(
        f"files in pack: {t['files_in_pack']} ({t['bytes_in_pack_excluding_manifest']} bytes); "
        f"referenced by hash: {t['files_referenced']} ({t['bytes_referenced']} bytes)"
    )
    for it in manifest["items"]:
        print(
            f"  {it['status']:7} {it['id']}: copied {it['files_copied']}, referenced {it['files_referenced']}, generated {it['files_generated']}"
        )
    print(
        f"capability: {manifest['capability_counts']}; full release complete: {manifest['full_release_complete']}"
    )
    print(
        f"secret scan: {manifest['secret_scan']['redactions']} redactions in {manifest['secret_scan']['files_redacted']} files"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
