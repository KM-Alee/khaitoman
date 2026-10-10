"""Named service-protection presets (T11.3: "protect the tail" maps to a visible floor).

A preset is a declared planning policy, not a measurement: its numerical floor is
shown to the user with every branch that uses it. Floors are fractions of each
field's fixed reference allowance (``field_service_ratio``).
"""

from __future__ import annotations

from typing import Literal

PresetId = Literal["tail-protect-standard", "tail-protect-strong", "all-fields-minimum"]

PRESETS: dict[str, dict] = {
    "tail-protect-standard": {
        "label": "Protect tail fields (standard)",
        "service_group": "tail",
        "minimum_service_ratio": 0.6,
        "basis": "assumption",
        "note": "Every tail field receives at least 60% of its fixed reference canal allowance.",
    },
    "tail-protect-strong": {
        "label": "Protect tail fields (strong)",
        "service_group": "tail",
        "minimum_service_ratio": 0.75,
        "basis": "assumption",
        "note": "Every tail field receives at least 75% of its fixed reference canal allowance.",
    },
    "all-fields-minimum": {
        "label": "Minimum service for all fields",
        "service_group": "all",
        "minimum_service_ratio": 0.5,
        "basis": "assumption",
        "note": "Every field receives at least 50% of its fixed reference canal allowance.",
    },
}


def preset_list() -> list[dict]:
    return [{"preset_id": k, **v} for k, v in PRESETS.items()]
