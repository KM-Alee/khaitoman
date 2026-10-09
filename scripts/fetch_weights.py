"""Download Delineate Anything weights into data/models and record SHA-256 (T2.1, T14).

Runs inside the vision container: `make vision-weights`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from huggingface_hub import hf_hub_download

REPO = "MykolaL/DelineateAnything"
FILES = ["DelineateAnything.pt", "DelineateAnythingv2.pt", "DelineateAnything-S.pt"]
DEST = Path("/app/data/models/delineate-anything")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    lines = []
    for name in FILES:
        path = Path(hf_hub_download(REPO, name, local_dir=DEST))
        digest = sha256(path)
        lines.append(f"{digest}  {name}")
        print(f"{name}: {path.stat().st_size} bytes sha256={digest}")
    (DEST / "SHA256SUMS").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
