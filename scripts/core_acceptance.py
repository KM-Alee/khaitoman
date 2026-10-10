"""core-acceptance v1.

Runs each collected test whose name contains AT01–AT18 once. Exits nonzero when
an executed test fails. Prints every AT id that still has no such test.

v1 is not the G-CORE completion gate and it does not mark AT13–AT18 passed.
It does not rebuild libraries, retrain models, or start copilot evaluation.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AT_IDS = tuple(f"AT{n:02d}" for n in range(1, 19))
LATE_IDS = frozenset(f"AT{n:02d}" for n in range(13, 19))
_AT_ID = re.compile(r"(?i)(?<![A-Z0-9])AT(0[1-9]|1[0-8])(?![0-9])")


def at_ids_in(name: str) -> set[str]:
    return {f"AT{match.group(1)}" for match in _AT_ID.finditer(name)}


def status_for(at: str, outcomes: list[str]) -> str:
    if not outcomes:
        return "no_test"
    if any(item in {"failed", "error"} for item in outcomes):
        return "failed"
    if all(item == "skipped" for item in outcomes):
        return "skipped"
    if any(item == "skipped" for item in outcomes):
        return "partial"
    if at in LATE_IDS:
        return "executed_not_marked_passed"
    return "passed"


def marked_passed(status: str) -> bool:
    return status == "passed"


def render(statuses: dict[str, str], counts: dict[str, int], pytest_code: int) -> str:
    absent = [at for at in AT_IDS if statuses[at] == "no_test"]
    lines = [
        "core-acceptance: v1",
        "g_core: false",
        "m7_completion_gate: false",
        "at13_at18_marked_passed: false",
        "batches_launched: none",
        f"pytest_exit: {pytest_code}",
        (
            "note: v1 runs existing AT tests once, fails on executed failures, and lists AT ids "
            "with no test. It is not the G-CORE completion gate and does not mark AT13-AT18 passed."
        ),
    ]
    for at in AT_IDS:
        lines.append(
            f"{at} status={statuses[at]} tests={counts[at]} "
            f"marked_passed={str(marked_passed(statuses[at])).lower()}"
        )
    lines.append("absent: " + (",".join(absent) if absent else "(none)"))
    return "\n".join(lines) + "\n"


def exit_code(statuses: dict[str, str], pytest_code: int) -> int:
    if pytest_code != 0:
        return pytest_code
    if any(status == "failed" for status in statuses.values()):
        return 1
    return 0


def _bounded_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    env["AABFLOW_SCIENCE_WORKERS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["NUMBA_NUM_THREADS"] = "1"
    return env


def _pytest(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--rootdir",
        str(ROOT),
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
        *args,
    ]
    return subprocess.run(
        cmd, cwd=ROOT, env=_bounded_env(), text=True, capture_output=True, check=False
    )


def _nodeids(collect: subprocess.CompletedProcess[str], target: str) -> list[str]:
    base = Path(target)
    if base.is_file():
        base = base.parent
    found = []
    for line in (collect.stdout or "").splitlines():
        nodeid = line.strip().split()[0] if line.strip() else ""
        if "::" not in nodeid or nodeid.startswith("ERROR"):
            continue
        if not at_ids_in(nodeid.split("::")[-1]):
            continue
        file_part, _, rest = nodeid.partition("::")
        if file_part.endswith("test_core_acceptance.py"):
            continue
        path = Path(file_part)
        if not path.is_absolute():
            rooted = ROOT / file_part
            path = rooted if rooted.exists() else base / file_part
        found.append(f"{path}::{rest}")
    return found


def _junit_outcomes(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    rows = []
    for case in root.findall(".//testcase"):
        name = case.get("name") or ""
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        rows.append((name, outcome))
    return rows


def _statuses(outcomes: list[tuple[str, str]]) -> tuple[dict[str, str], dict[str, int]]:
    grouped = {at: [] for at in AT_IDS}
    for name, outcome in outcomes:
        for at in at_ids_in(name):
            grouped[at].append(outcome)
    statuses = {at: status_for(at, grouped[at]) for at in AT_IDS}
    counts = {at: len(grouped[at]) for at in AT_IDS}
    return statuses, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AabFlow core-acceptance v1")
    parser.add_argument("--tests", default="tests", help="pytest path to collect once")
    args = parser.parse_args(argv)
    target = str(Path(args.tests).resolve()) if Path(args.tests).is_absolute() else args.tests
    print("core-acceptance v1: collecting AT tests once", flush=True)
    collected = _pytest(["--collect-only", "-q", target])
    sys.stdout.write(collected.stdout or "")
    sys.stderr.write(collected.stderr or "")
    if collected.returncode not in (0, 5):
        print("core-acceptance v1: collection failed", flush=True)
        return collected.returncode
    nodeids = _nodeids(collected, target)
    with tempfile.TemporaryDirectory(prefix="aabflow-core-acceptance-") as tmp:
        junit = Path(tmp) / "junit.xml"
        if nodeids:
            print(f"core-acceptance v1: running {len(nodeids)} AT tests once", flush=True)
            ran = _pytest(["-q", "--tb=line", f"--junitxml={junit}", *nodeids])
            sys.stdout.write(ran.stdout or "")
            sys.stderr.write(ran.stderr or "")
            pytest_code = ran.returncode
        else:
            pytest_code = 0
        statuses, counts = _statuses(_junit_outcomes(junit))
    summary = render(statuses, counts, pytest_code)
    sys.stdout.write(summary)
    return exit_code(statuses, pytest_code)


if __name__ == "__main__":
    sys.exit(main())
