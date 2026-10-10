"""Untouched external evaluation of the trained surrogate on a pilot's package weather.

usage: python scripts/science_surrogate_external.py <pilot_id>
Writes data/models/<current-training-version>/external-<pilot>.json.
"""

from __future__ import annotations

import json
import sys

from aabflow.surrogate.training import external_evaluation


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    print(json.dumps(external_evaluation(sys.argv[1]), indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
