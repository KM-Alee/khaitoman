"""M7 / AT17: run the thirty-case copilot evaluation (T11.8) against the configured model.

    docker compose run --rm --no-deps api python scripts/copilot_eval.py [--cases C01,C05] [--reps 3]

Writes evidence/copilot/eval-<ts>.json and .md; exits non-zero unless >=90% of
executions pass and every critical execution passes.
"""

from aabflow.copilot.evaluations.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
