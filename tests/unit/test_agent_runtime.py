"""Runtime isolation regressions using explicitly synthetic Docker/Git fixtures.

No test launches Docker, reads a real secret, or mutates the project checkout.
The suite itself is executed inside the API image.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "scripts/agent_runtime.sh"
FAKE_DOCKER = r'''#!/usr/bin/env python3
"""Synthetic image registry and Compose call recorder: tests only."""
import json
import os
import sys
from pathlib import Path
args = sys.argv[1:]
registry_path = Path(os.environ["FIXTURE_REGISTRY"])
images = json.loads(registry_path.read_text())
with Path(os.environ["FIXTURE_DOCKER_LOG"]).open("a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["image", "inspect"]:
    if args[2] not in images:
        print("fixture image missing", file=sys.stderr)
        sys.exit(1)
    print(images[args[2]])
elif args[:2] == ["image", "tag"]:
    images[args[3]] = images.get(args[2], args[2])
    registry_path.write_text(json.dumps(images))
elif args[:1] == ["run"]:
    embedded = json.loads(Path(os.environ["FIXTURE_EMBEDDED_LOCKS"]).read_text())
    image = next((arg for arg in args if arg in images or arg in images.values() or arg in embedded), None)
    image_id = images.get(image, image)
    if image_id not in embedded:
        print("fixture embedded lock unavailable", file=sys.stderr)
        sys.exit(1)
    matched = False
    for path, digest in embedded[image_id].items():
        if any(path in arg for arg in args):
            mismatch = os.environ.get("FIXTURE_IMAGE_LOCK_MISMATCH")
            if mismatch and mismatch in image_id:
                digest = "0" * 64
            print(digest + "  " + path)
            matched = True
    if not matched:
        print("unsupported fixture lock query", file=sys.stderr)
        sys.exit(1)
    if os.environ.get("FIXTURE_RETAG_DURING_VERIFY") and image_id == "sha256:fixture-api":
        # Simulate the other contributor rebuilding the shared source tag.
        images["aabflow-dev:local"] = "sha256:fixture-unverified-replacement"
        registry_path.write_text(json.dumps(images))
elif args[0] == "compose":
    project = args[args.index("-p") + 1]
    # Every invocation must explicitly avoid automatic .env loading.
    if "--env-file" not in args or args[args.index("--env-file") + 1] != "/dev/null":
        print("fixture rejected secret environment loading", file=sys.stderr)
        sys.exit(1)
    index = 1
    while args[index] in ("--env-file", "-p", "-f", "--profile"):
        index += 2
    command = args[index]
    if command == "build":
        suffixes = {"api": "dev", "web": "web", "demo": "demo", "e2e": "e2e", "vision": "vision"}
        for service in args[index + 1:]:
            if service in suffixes:
                key = project + "-" + suffixes[service] + ":local"
                images[key] = images.get(key, "fixture-image") + "-rebuilt"
        registry_path.write_text(json.dumps(images))
else:
    print("unsupported fixture command", file=sys.stderr)
    sys.exit(1)
'''
FAKE_GIT = r'''#!/usr/bin/env python3
"""Synthetic branch and ignored-file listing: tests only."""
import json
import os
import sys
from pathlib import Path
args = sys.argv[1:]
root = Path.cwd()
if args[:1] == ["-C"]:
    root = Path(args[1])
    args = args[2:]
if args == ["branch", "--show-current"]:
    if os.environ.get("FIXTURE_GIT_BRANCH_ERROR"):
        print("synthetic invalid gitfile", file=sys.stderr)
        sys.exit(1)
    print((root / "fixture-branch").read_text().strip())
elif args == ["rev-parse", "--show-toplevel"]:
    print(root)
elif args[:1] == ["ls-files"]:
    if os.environ.get("FIXTURE_GIT_FAIL_LIST"):
        print("synthetic ignored listing failed", file=sys.stderr)
        sys.exit(1)
    prefix = args[args.index("--") + 1] + "/"
    entries = json.loads((root / "fixture-ignored.json").read_text())
    for entry in entries:
        if entry.startswith(prefix):
            sys.stdout.buffer.write(entry.encode() + b"\0")
else:
    print("unsupported fixture git command", file=sys.stderr)
    sys.exit(1)
'''


class Runtime:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "linked-worker"
        self.root.mkdir()
        (self.root / "scripts").mkdir()
        shutil.copy2(HELPER, self.root / "scripts/agent_runtime.sh")
        (self.root / ".git").write_text("gitdir: /synthetic/common/worktrees/worker\n")
        (self.root / "fixture-branch").write_text("feat/synthetic-worker\n")
        (self.root / "compose.yaml").write_text("services: {}\n")
        (self.root / "compose.gpu.yaml").write_text("services: {}\n")
        (self.root / "uv.lock").write_text("synthetic python lock\n")
        (self.root / "pyproject.toml").write_text('[project]\nname="synthetic-test-fixture"\n')
        (self.root / "web").mkdir()
        (self.root / "web/package-lock.json").write_text('{"synthetic":"node lock"}\n')
        (self.root / "web/package.json").write_text('{"name":"synthetic-test-fixture"}\n')
        binary = tmp_path / "bin"
        binary.mkdir()
        for name, content in (("docker", FAKE_DOCKER), ("git", FAKE_GIT)):
            path = binary / name
            path.write_text(content)
            path.chmod(0o755)
        self.registry = tmp_path / "registry.json"
        self.log = tmp_path / "docker-calls.jsonl"
        self.registry.write_text(
            json.dumps(
                {
                    "aabflow-dev:local": "sha256:fixture-api",
                    "aabflow-web-dev:local": "sha256:fixture-web",
                    "aabflow:local": "sha256:fixture-demo",
                    "aabflow-e2e:local": "sha256:fixture-e2e",
                    "aabflow-vision:local": "sha256:fixture-vision",
                }
            )
        )
        self.env = {
            "PATH": f"{binary}:/usr/local/bin:/usr/bin:/bin",
            "FIXTURE_REGISTRY": str(self.registry),
            "FIXTURE_DOCKER_LOG": str(self.log),
        }
        embedded = tmp_path / "embedded-locks.json"
        python_hash = hashlib.sha256((self.root / "uv.lock").read_bytes()).hexdigest()
        node_hash = hashlib.sha256((self.root / "web/package-lock.json").read_bytes()).hexdigest()
        python_manifest = hashlib.sha256((self.root / "pyproject.toml").read_bytes()).hexdigest()
        node_manifest = hashlib.sha256((self.root / "web/package.json").read_bytes()).hexdigest()
        embedded.write_text(
            json.dumps(
                {
                    "sha256:fixture-api": {
                        "/app/uv.lock": python_hash,
                        "/app/pyproject.toml": python_manifest,
                    },
                    "sha256:fixture-web": {
                        "/app/web/package-lock.json": node_hash,
                        "/app/web/package.json": node_manifest,
                    },
                    "sha256:fixture-e2e": {
                        "/app/web/package-lock.json": node_hash,
                        "/app/web/package.json": node_manifest,
                    },
                }
            )
        )
        self.env["FIXTURE_EMBEDDED_LOCKS"] = str(embedded)

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/agent_runtime.sh", *args],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )

    def init(self):
        result = self.run("init", "fixture", "2")
        assert result.returncode == 0, result.stderr

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def runtime(tmp_path):
    return Runtime(tmp_path)


def test_init_refuses_main_before_any_docker_action(runtime):
    (runtime.root / "fixture-branch").write_text("main\n")
    result = runtime.run("init", "fixture", "1")
    assert result.returncode != 0
    assert "main" in result.stderr
    assert not runtime.log.exists()
    assert not (runtime.root / ".agent-work").exists()


def test_init_requires_linked_worktree(runtime):
    (runtime.root / ".git").unlink()
    (runtime.root / ".git").mkdir()
    result = runtime.run("init", "fixture", "1")
    assert result.returncode != 0
    assert "linked Git worktree" in result.stderr
    assert not runtime.log.exists()


def test_init_refuses_invalid_linked_gitfile(runtime):
    runtime.env["FIXTURE_GIT_BRANCH_ERROR"] = "1"
    result = runtime.run("init", "fixture", "1")
    assert result.returncode != 0
    assert not runtime.log.exists()


def test_init_refuses_detached_worker_head(runtime):
    (runtime.root / "fixture-branch").write_text("\n")
    result = runtime.run("init", "fixture", "1")
    assert result.returncode != 0
    assert not runtime.log.exists()


@pytest.mark.parametrize("location", ["worker", "ancestor"])
def test_init_refuses_secret_filenames_without_opening_them(runtime, location):
    # A FIFO would hang if opened. It contains no secret or real environment data.
    path = runtime.root / ".env.fixture" if location == "worker" else runtime.root.parent / ".env"
    os.mkfifo(path)
    result = runtime.run("init", "fixture", "1")
    assert result.returncode != 0
    assert "environment files" in result.stderr or ".env" in result.stderr
    assert not runtime.log.exists()


def test_init_allows_template_filename_without_opening_it(runtime):
    # The tracked template is not an environment input; FIFO proves no content read.
    os.mkfifo(runtime.root / ".env.example")
    runtime.init()


@pytest.mark.parametrize("service", ["api", "web", "e2e"])
def test_init_refuses_dependency_locks_that_differ_from_original_image(runtime, service):
    runtime.env["FIXTURE_IMAGE_LOCK_MISMATCH"] = service
    result = runtime.run("init", "fixture", "1")
    assert result.returncode != 0
    assert not (runtime.root / ".agent-work/api.image").exists()
    assert not any(call[:2] == ["image", "tag"] for call in runtime.calls())


@pytest.mark.parametrize("path", ["pyproject.toml", "web/package.json"])
def test_init_refuses_changed_manifest_even_if_lockfile_is_unchanged(runtime, path):
    (runtime.root / path).write_text("synthetic changed manifest\n")
    result = runtime.run("init", "fixture", "1")
    assert result.returncode != 0
    assert not any(call[:2] == ["image", "tag"] for call in runtime.calls())


def test_initial_frozen_demo_requires_explicit_worker_build(runtime):
    runtime.init()
    before = runtime.run("compose", "--profile", "demo", "run", "--rm", "demo", "true")
    assert before.returncode != 0
    built = runtime.run("compose", "--profile", "demo", "build", "demo")
    assert built.returncode == 0, built.stderr
    after = runtime.run("compose", "--profile", "demo", "run", "--rm", "demo", "true")
    assert after.returncode == 0, after.stderr


def test_init_retags_the_exact_verified_image_id_even_if_shared_tag_changes(runtime):
    runtime.env["FIXTURE_RETAG_DURING_VERIFY"] = "1"
    runtime.init()
    images = json.loads(runtime.registry.read_text())
    assert images["aabflow-dev:local"] == "sha256:fixture-unverified-replacement"
    assert images["aabflow-worker-fixture-dev:local"] == "sha256:fixture-api"


def test_compose_uses_private_images_ports_and_explicit_empty_env(runtime):
    runtime.init()
    override = (runtime.root / ".agent-work/compose.yaml").read_text()
    assert "127.0.0.1:18002:8000" in override
    assert "127.0.0.1:15172:5173" in override
    assert "aabflow-worker-fixture-dev:local" in override
    assert "aabflow-worker-fixture-web:local" in override
    assert "AABFLOW_DB_PATH: /app/data/agent.sqlite" in override
    assert override.count("env_file: !reset []") == 2
    result = runtime.run("compose", "--gpu", "run", "--rm", "--no-deps", "-T", "api", "true")
    assert result.returncode == 0, result.stderr
    calls = [call for call in runtime.calls() if call[0] == "compose"]
    for call in calls:
        assert call[call.index("--env-file") + 1] == "/dev/null"
        assert call[call.index("-p") + 1] == "aabflow-worker-fixture"
    assert "compose.gpu.yaml" in calls[-1]
    for call in runtime.calls():
        if call[0] == "run":
            assert call[call.index("--network") + 1] == "none"
            assert "--volume" not in call and "-v" not in call
    images = json.loads(runtime.registry.read_text())
    assert images["aabflow-worker-fixture-dev:local"] == "sha256:fixture-api"
    assert images["aabflow-worker-fixture-web:local"] == "sha256:fixture-web"


def test_program_argument_build_does_not_bless_changed_lock(runtime):
    runtime.init()
    image_record = runtime.root / ".agent-work/api.image"
    lock_record = runtime.root / ".agent-work/api.locks"
    before = (image_record.read_text(), lock_record.read_text())
    (runtime.root / "uv.lock").write_text("synthetic changed python lock\n")
    result = runtime.run("compose", "run", "--rm", "api", "echo", "build")
    assert result.returncode != 0
    assert "lockfiles changed" in result.stderr
    assert (image_record.read_text(), lock_record.read_text()) == before
    assert not any(call[0] == "compose" and "run" in call for call in runtime.calls())


def test_build_refreshes_only_explicit_service_lock_and_image(runtime):
    runtime.init()
    root = runtime.root / ".agent-work"
    old_web = ((root / "web.locks").read_text(), (root / "web.image").read_text())
    old_api_image = (root / "api.image").read_text()
    (runtime.root / "uv.lock").write_text("synthetic changed python lock\n")
    (runtime.root / "web/package-lock.json").write_text('{"synthetic":"changed node lock"}\n')
    result = runtime.run("compose", "build", "api")
    assert result.returncode == 0, result.stderr
    assert (root / "api.image").read_text() != old_api_image
    assert (root / "api.image").read_text().strip() == json.loads(runtime.registry.read_text())[
        "aabflow-worker-fixture-dev:local"
    ]
    assert ((root / "web.locks").read_text(), (root / "web.image").read_text()) == old_web
    assert runtime.run("compose", "run", "--rm", "api", "true").returncode == 0
    web = runtime.run("compose", "run", "--rm", "web", "true")
    assert web.returncode != 0
    assert "lockfiles changed" in web.stderr
    rebuilt_web = runtime.run("compose", "build", "--no-cache", "web")
    assert rebuilt_web.returncode == 0, rebuilt_web.stderr
    assert runtime.run("compose", "run", "--rm", "web", "true").returncode == 0


@pytest.mark.parametrize("damage", ["missing", "retagged"])
def test_run_refuses_missing_or_retagged_image(runtime, damage):
    runtime.init()
    images = json.loads(runtime.registry.read_text())
    if damage == "missing":
        del images["aabflow-worker-fixture-dev:local"]
    else:
        images["aabflow-worker-fixture-dev:local"] = "sha256:fixture-someone-elses-image"
    runtime.registry.write_text(json.dumps(images))
    result = runtime.run("compose", "run", "--rm", "api", "true")
    assert result.returncode != 0
    assert not any(call[0] == "compose" and "run" in call for call in runtime.calls())


@pytest.mark.parametrize("args", [("up", "-d"), ("up", "--build", "api")])
def test_up_cannot_bypass_service_checks_or_explicit_build(runtime, args):
    runtime.init()
    result = runtime.run("compose", *args)
    assert result.returncode != 0
    assert not any(call[0] == "compose" and "up" in call for call in runtime.calls())


def test_seed_listing_errors_are_not_reported_as_success(runtime, tmp_path):
    runtime.init()
    seed = tmp_path / "synthetic-seed"
    seed.mkdir()
    runtime.env["FIXTURE_GIT_FAIL_LIST"] = "1"
    result = runtime.run("seed", str(seed), "raw")
    assert result.returncode != 0
    assert "Privately copied" not in result.stdout


def test_seed_copies_only_missing_ignored_assets_and_keeps_metadata(runtime, tmp_path):
    runtime.init()
    seed = tmp_path / "synthetic-seed"
    seed.mkdir()
    entries = [
        "data/raw/missing.bin",
        "data/raw/existing.bin",
        "data/raw/manifest.json",
        "data/raw/app.sqlite",
        "data/raw/app.sqlite-wal",
        "data/raw/app.sqlite-shm",
        "data/raw/.env.fixture",
        "data/raw/link.bin",
    ]
    (seed / "fixture-ignored.json").write_text(json.dumps(entries))
    for entry in entries:
        path = seed / entry
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.name == ".env.fixture":
            os.mkfifo(path)
        elif path.name == "link.bin":
            path.symlink_to(seed / "data/raw/missing.bin")
        else:
            path.write_text("synthetic seed data\n")
    worker_data = runtime.root / "data/raw"
    worker_data.mkdir(parents=True)
    (worker_data / "existing.bin").write_text("worker-owned existing asset\n")
    (worker_data / "manifest.json").write_text("worker tracked metadata fixture\n")
    result = runtime.run("seed", str(seed), "raw")
    assert result.returncode == 0, result.stderr
    assert (worker_data / "missing.bin").read_text() == "synthetic seed data\n"
    assert (worker_data / "existing.bin").read_text() == "worker-owned existing asset\n"
    assert (worker_data / "manifest.json").read_text() == "worker tracked metadata fixture\n"
    assert not (worker_data / ".env.fixture").exists()
    assert not (worker_data / "link.bin").exists()
    assert not (worker_data / "app.sqlite").exists()
    assert not (worker_data / "app.sqlite-wal").exists()
    assert not (worker_data / "app.sqlite-shm").exists()
