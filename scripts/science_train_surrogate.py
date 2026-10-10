"""Train and evaluate the crop-specific LightGBM surrogates (T8); writes a versioned data/models/ directory.

Exit code 0 only when every crop passes its T8.3 gates; failures are reported, never hidden.
"""

from __future__ import annotations

import json

from aabflow.surrogate.training import train_all


def main() -> int:
    summary = train_all()
    print(json.dumps(summary, indent=1, default=str))
    return 0 if summary["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
