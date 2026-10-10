"""Proof-package builder (PRD §13.3). Every repository below is a synthetic tmp-dir FIXTURE;
none of these pilots, runs, logs or keys are real evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_evidence_pack", Path(__file__).resolve().parents[2] / "scripts/build_evidence_pack.py"
)
assert _SPEC and _SPEC.loader
pack_mod = importlib.util.module_from_spec(_SPEC)
sys.modules["build_evidence_pack"] = pack_mod  # dataclasses resolve the module
_SPEC.loader.exec_module(pack_mod)

NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)
FAKE_KEY = "sk-proj-" + "FIXTUREONLYnotarealkey0123456789"  # fixture, never a real credential
OPEN_LICENCES = ["CC-BY-4.0", "copernicus-sentinel-data-terms"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


def fixture_pilot(root: Path, pid: str, licences: list[str], files: dict[str, bytes]) -> None:
    pkg = root / "data" / "pilots" / pid / "fixture-v1"
    entries = []
    for name, data in files.items():
        write(pkg / name, data)
        entries.append({"path": name, "size_bytes": len(data), "sha256": sha(data), "kind": "x"})
    manifest = {
        "manifest_version": "1",
        "pilot_id": pid,
        "pilot_version": "fixture-v1",
        "licenses": licences,
        "source_ids": [f"delineate:fixturekey-{pid}"],
        "files": entries,
    }
    write(pkg / "manifest.json", json.dumps(manifest))


def fixture_run(root: Path, run_id: str) -> Path:
    rdir = root / "data" / "runs" / run_id
    files = {
        "run.json": b'{"run_id": "fixture"}',
        "solver.json": b'{"status": "OPTIMAL", "bound": 1.0}',
        "ledger.parquet": b"PAR1-fixture-ledger-bytes",
    }
    for name, data in files.items():
        write(rdir / name, data)
    manifest = {
        "run_id": run_id,
        "files": [{"path": n, "sha256": sha(d), "size_bytes": len(d)} for n, d in files.items()],
    }
    write(rdir / "manifest.json", json.dumps(manifest))
    return rdir


STATUS_MD = """# Build status (FIXTURE)

## Features (PRD §3)

| ID | Feature | Milestone | Status | Evidence |
|---|---|---|---|---|
| F01 | Fixture workspace | M1 | passed | `evidence/commands/fixture.log` and `evidence/missing-fixture.json` |
| F02 | Fixture AI | M1 | in_progress | `evidence/benchmarks/fixture-*.json` |
| F03 | Fixture onboarding | M1 | blocked | needs a real partner |

## Acceptance tests (PRD §11.2)

| ID | Summary | Milestone | Status | Evidence |
|---|---|---|---|---|
| AT01 | Fixture pilots | M1 | passed | `test_at01_fixture_case` |
| AT02 | Fixture crops | M2 | failed | `tests/unit/test_fixture_cases.py::test_at01_fixture_case` |
| AT17 | Fixture copilot | M7 | passed | `evidence/commands/fixture.log` |
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "fixture-repo"
    write(root / "docs" / "STATUS.md", STATUS_MD)
    write(root / ".env", f"OPENAI_API_KEY={FAKE_KEY}\n")
    write(
        root / "tests" / "unit" / "test_fixture_cases.py",
        "def test_at01_fixture_case():\n    pass\n",
    )
    write(
        root / "data" / "pilots" / "index.json",
        json.dumps(
            [
                {"pilot_id": "open-pilot", "pilot_version": "fixture-v1"},
                {"pilot_id": "closed-pilot", "pilot_version": "fixture-v1"},
            ]
        ),
    )
    fixture_pilot(
        root,
        "open-pilot",
        OPEN_LICENCES,
        {"fields.geojson": b'{"type": "FeatureCollection"}', "big.tif": b"\0" * 4096},
    )
    fixture_pilot(root, "closed-pilot", ["fixture-proprietary"], {"fields.geojson": b"{}"})
    write(root / "vision" / "runs" / "fixturekey-open-pilot" / "run.json", '{"ok": true}')
    write(
        root / "evidence" / "commands" / "fixture.log",
        f"fixture log line\nexport OPENAI_API_KEY={FAKE_KEY}\n",
    )
    write(root / "evidence" / "benchmarks" / "fixture-bench.json", '{"p50_ms": 1}')
    write(root / "evidence" / "rehearsal" / ".gitkeep", "")
    write(root / "data" / "libraries" / "p" / "s" / "latest.json", '{"policies": 1}')
    write(root / "data" / "libraries" / "p" / "s" / "abc" / "library.json", "{}")
    write(root / "data" / "libraries" / "p" / "s" / "abc" / "policies.jsonl", "{}\n" * 2000)
    good = fixture_run(root, "run_fixture_good")
    fixture_run(root, "run_fixture_orphan")
    db = root / "data" / "app.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE runs (run_id TEXT, plan_kind TEXT, outcome TEXT, solver_status TEXT,"
        " candidate_library_hash TEXT, run_dir TEXT, manifest_sha256 TEXT, analysis_id TEXT);"
        "CREATE TABLE analyses (analysis_id TEXT, kind TEXT, result TEXT);"
        "CREATE TABLE reports (report_id TEXT, report_dir TEXT);"
        "CREATE TABLE idempotency (key TEXT, response TEXT);"
    )
    conn.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
        (
            "run_fixture_good",
            "P",
            "plan",
            "OPTIMAL",
            "fixturehash",
            f"/app/data/runs/{good.name}",
            "x",
            "ana_fixture",
        ),
    )
    conn.execute("INSERT INTO analyses VALUES ('ana_fixture', 'frontier', '{}')")
    conn.execute("INSERT INTO idempotency VALUES ('k', 'cached response')")
    conn.commit()
    conn.close()
    return root


def build(repo: Path, **kw) -> tuple[Path, dict]:
    pack = pack_mod.build(repo, repo / "evidence" / "pack", now=NOW, max_file_bytes=2048, **kw)
    return pack, json.loads((pack / "manifest.json").read_text())


def test_pack_files_match_manifest_hashes(repo: Path) -> None:
    pack, manifest = build(repo)
    assert pack.name == "20261010T120000Z"
    listed = {f["path"]: f for f in manifest["files"] if f["path"]}
    on_disk = {p.relative_to(pack).as_posix() for p in pack.rglob("*") if p.is_file()} - {
        "manifest.json"
    }
    assert on_disk == set(listed)
    for rel, entry in listed.items():
        data = (pack / rel).read_bytes()
        assert entry["size_bytes"] == len(data) and entry["sha256"] == sha(data)
        assert entry["source"]
    assert manifest["totals"]["files_in_pack"] == len(listed) + 1
    # The tmp build folder was renamed into place; nothing half-written remains.
    assert [p.name for p in (repo / "evidence" / "pack").iterdir()] == [pack.name]


def test_oversize_and_unlicensed_files_are_referenced_not_copied(repo: Path) -> None:
    pack, manifest = build(repo)
    refs = {f["source"]: f for f in manifest["files"] if f["mode"] == "referenced"}
    big = refs["data/pilots/open-pilot/fixture-v1/big.tif"]
    assert big["path"] is None and big["sha256"] == sha(b"\0" * 4096)
    assert "threshold" in big["reason"]
    assert not (pack / "pilots/open-pilot/fixture-v1/big.tif").exists()
    closed = refs["data/pilots/closed-pilot/fixture-v1/fields.geojson"]
    assert "redistribution" in closed["reason"]
    assert not (pack / "pilots/closed-pilot/fixture-v1/fields.geojson").exists()
    assert (pack / "pilots/open-pilot/fixture-v1/fields.geojson").is_file()
    assert any(s.endswith("policies.jsonl") for s in refs)


def test_secrets_are_redacted_and_env_never_read(repo: Path) -> None:
    pack, manifest = build(repo)
    for p in pack.rglob("*"):
        if p.is_file():
            assert FAKE_KEY.encode() not in p.read_bytes(), p
    assert not any(".env" in (f["source"] or "") for f in manifest["files"])
    log = next(f for f in manifest["files"] if f["source"] == "evidence/commands/fixture.log")
    assert log["redactions"] >= 1
    assert log["source_sha256"] == sha((repo / "evidence/commands/fixture.log").read_bytes())
    assert "[REDACTED]" in (pack / log["path"]).read_text()
    assert manifest["secret_scan"]["redactions"] >= 1
    assert not (pack / "app-db" / "idempotency.json").exists()


def test_capability_report_statuses_and_cited_paths(repo: Path) -> None:
    pack, manifest = build(repo)
    report = json.loads((pack / "capability-report.json").read_text())
    by_id = {e["id"]: e for e in report["entries"]}
    assert len(by_id) == 38
    assert by_id["AT17"]["status"] != "passed" and by_id["AT17"]["status_md"] == "passed"
    assert by_id["F01"]["status"] == "passed"
    f01 = {r["cited"]: r for r in by_id["F01"]["artifact_refs"]}
    assert f01["evidence/commands/fixture.log"]["exists"]
    assert f01["evidence/commands/fixture.log"]["in_pack"] == ["evidence/commands/fixture.log"]
    assert not f01["evidence/missing-fixture.json"]["exists"]
    assert any("missing-fixture" in w for w in by_id["F01"]["warnings"])
    assert by_id["F02"]["status"] == "not_run"
    assert by_id["F02"]["artifact_refs"][0]["resolved"] == [
        "evidence/benchmarks/fixture-bench.json"
    ]
    assert by_id["F03"]["status"] == "blocked"
    assert by_id["AT02"]["status"] == "failed"
    at01 = by_id["AT01"]["artifact_refs"][0]
    assert at01["resolved"] == ["tests/unit/test_fixture_cases.py::test_at01_fixture_case"]
    assert by_id["AT05"]["status"] == "not_run"
    assert "row missing from docs/STATUS.md" in by_id["AT05"]["warnings"]
    assert report["full_release_complete"] is False
    assert manifest["capability_counts"] == report["counts"]
    md = (pack / "capability-report.md").read_text()
    assert "| AT17 | Fixture copilot | not_run | passed |" in md
    assert "`evidence/missing-fixture.json` (MISSING)" in md


def test_runs_items_and_missing_proof_listed(repo: Path) -> None:
    pack, manifest = build(repo)
    runs = {r["run_id"]: r for r in manifest["runs"]}
    assert runs["run_fixture_good"]["manifest_check"] == "verified"
    assert runs["run_fixture_good"]["has_ledger"] and runs["run_fixture_good"]["has_solver_log"]
    assert (pack / "runs/run_fixture_good/ledger.parquet").is_file()
    assert not (pack / "runs/run_fixture_orphan").exists()
    items = {i["id"]: i for i in manifest["items"]}
    assert any("run_fixture_orphan" in n for n in items["completed_runs"]["notes"])
    assert items["analyses"]["status"] == "found"
    # An empty reports table, no transcripts and only a .gitkeep under rehearsal are missing.
    assert {"reports", "chat_eval_transcripts", "rehearsal"} <= set(manifest["missing_items"])
    assert items["raw_inference"]["status"] == "found"
    assert any(
        "fixturekey-closed-pilot" in n and "no run record" in n
        for n in items["raw_inference"]["notes"]
    )


def test_tampered_run_is_reported(repo: Path) -> None:
    (repo / "data/runs/run_fixture_good/ledger.parquet").write_bytes(b"PAR1-changed")
    _, manifest = build(repo)
    assert manifest["runs"][0]["manifest_check"] == "hash_mismatch"


def test_existing_pack_is_never_overwritten(repo: Path) -> None:
    pack, _ = build(repo)
    before = (pack / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        build(repo)
    assert (pack / "manifest.json").read_bytes() == before
    assert [p.name for p in (repo / "evidence" / "pack").iterdir()] == [pack.name]


@pytest.mark.parametrize(
    ("text", "redacted"),
    [
        (f'"api_key": "{FAKE_KEY}"', True),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345", True),
        ("GITHUB_TOKEN=ghp_" + "A" * 36, True),
        ('"candidate_library_hash": "' + "a" * 64 + '"', False),
        ('"input_tokens": 1234, "model": "fixture-model"', False),
        ("tokenize = 'porter unicode61'", False),
    ],
)
def test_scrub_text(text: str, redacted: bool) -> None:
    out, n = pack_mod.scrub_text(text)
    assert (n > 0) is redacted
    assert ("[REDACTED]" in out) is redacted
