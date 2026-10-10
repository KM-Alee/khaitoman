"""core-acceptance v1 runner checks. These names do not claim an AT id."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "core_acceptance.py"


def _runner():
    spec = importlib.util.spec_from_file_location("core_acceptance_v1", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_core_acceptance_v1_classifies_ids_and_withholds_late_passes():
    runner = _runner()
    assert runner.at_ids_in("test_at12_pond_land_removed_once") == {"AT12"}
    assert runner.at_ids_in("test_at05_and_at08") == {"AT05", "AT08"}
    assert runner.at_ids_in("test_at1_partial") == set()
    assert runner.status_for("AT05", ["passed"]) == "passed"
    assert runner.marked_passed("passed") is True
    assert runner.status_for("AT13", ["passed"]) == "executed_not_marked_passed"
    assert runner.marked_passed("executed_not_marked_passed") is False
    assert runner.status_for("AT07", ["failed"]) == "failed"
    assert runner.status_for("AT01", []) == "no_test"
    assert runner.marked_passed("no_test") is False
    source = SCRIPT.read_text()
    for banned in (
        "science_build_libraries",
        "science_train_surrogate",
        "science_library_adequacy",
        "copilot_eval",
        "compose.gpu",
    ):
        assert banned not in source


def _suite(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "test_sample.py"
    path.write_text(body)
    return tmp_path


def _run(suite: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--tests", str(suite)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _line(text: str, at: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{at} "):
            return line
    raise AssertionError(f"{at} missing from\n{text}")


def test_core_acceptance_v1_lists_absent_ids_and_withholds_late_ids(tmp_path):
    suite = _suite(
        tmp_path,
        "def test_at05_zero_capital_sample():\n    assert True\n\n"
        "def test_at13_screens_are_not_a_v1_pass():\n    assert True\n",
    )
    ran = _run(suite)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    text = ran.stdout
    assert "g_core: false" in text
    assert "m7_completion_gate: false" in text
    assert "at13_at18_marked_passed: false" in text
    assert "batches_launched: none" in text
    assert "status=passed" in _line(text, "AT05")
    assert "marked_passed=true" in _line(text, "AT05")
    at13 = _line(text, "AT13")
    assert "status=executed_not_marked_passed" in at13
    assert "status=passed" not in at13
    assert "marked_passed=false" in at13
    absent = next(line for line in text.splitlines() if line.startswith("absent:"))
    for missing in ("AT01", "AT06", "AT08", "AT12", "AT14", "AT18"):
        assert missing in absent


def test_core_acceptance_v1_fails_when_an_executed_test_fails(tmp_path):
    suite = _suite(
        tmp_path,
        "def test_at06_budget_change_fails():\n    assert False\n",
    )
    ran = _run(suite)
    assert ran.returncode != 0
    text = ran.stdout
    assert "status=failed" in _line(text, "AT06")
    assert "marked_passed=false" in _line(text, "AT06")
    assert "g_core: false" in text
    absent = next(line for line in text.splitlines() if line.startswith("absent:"))
    assert "AT05" in absent and "AT13" in absent
