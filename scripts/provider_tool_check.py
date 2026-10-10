"""M0: verify the configured model supports strict function calling via the Responses API (T11.4, T11.8).

Writes evidence/environment/provider-tools-<ts>.json. Prints no secrets.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
TOOL = {
    "type": "function",
    "name": "inspect_run",
    "description": "Read an existing run in the current pilot and return exact metrics.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}, "field_id": {"type": ["string", "null"]}},
        "required": ["run_id", "field_id"],
        "additionalProperties": False,
    },
}


def main() -> None:
    load_dotenv(ROOT / ".env")
    model = os.environ.get("AABFLOW_OPENAI_MODEL", "gpt-6-luna")
    client = OpenAI()
    t = time.perf_counter()
    first = client.responses.create(
        model=model,
        input="Inspect run run_demo for field field-007.",
        tools=[TOOL],
        tool_choice="required",
    )
    calls = [i for i in first.output if i.type == "function_call"]
    assert calls, "model returned no function call"
    args = json.loads(calls[0].arguments)
    second = client.responses.create(
        model=model,
        previous_response_id=first.id,
        input=[
            {
                "type": "function_call_output",
                "call_id": calls[0].call_id,
                "output": json.dumps({"production_kg": 1234.5, "status": "OPTIMAL"}),
            }
        ],
        tools=[TOOL],
    )
    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": model,
        "tool_call_name": calls[0].name,
        "tool_call_args": args,
        "followup_text_chars": len(second.output_text or ""),
        "latency_s": round(time.perf_counter() - t, 2),
        "request_ids": [first.id, second.id],
    }
    path = ROOT / "evidence/environment" / f"provider-tools-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
