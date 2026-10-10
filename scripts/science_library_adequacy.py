"""Run real denser-library checks on both pilots and both crop planning seasons (T5.7)."""

import json

from aabflow.optimizer.candidates.adequacy import REPRESENTATIVE_SEASONS, compare_density


def main():
    for pilot in ("pilot-a", "pilot-b"):
        for season in REPRESENTATIVE_SEASONS:
            report = compare_density(pilot, season)
            print(
                json.dumps({k: v for k, v in report.items() if k != "comparisons"}, indent=1),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
