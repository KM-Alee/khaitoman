"""Copilot tool registry (T11.2): declared, validated, role-scoped wrappers.

Every tool declares an argument model, read/create/compute/view semantics, a
timeout, a maximum result size, allowed roles and a plain activity message. The
provider sees strict JSON schemas generated from the argument models; arguments
returned by the model are validated again with Pydantic before dispatch.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from aabflow.domain.hashes import content_hash

Semantics = Literal["read", "create", "compute", "view"]
Role = Literal["planner", "viewer"]

ALL_ROLES: frozenset[str] = frozenset({"planner", "viewer"})
PLANNER: frozenset[str] = frozenset({"planner"})


class ToolArgs(BaseModel):
    """Base for tool argument models: unknown keys rejected, every key present in the schema."""

    model_config = ConfigDict(extra="forbid")


Handler = Callable[[Any, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[ToolArgs]
    semantics: Semantics
    handler: Handler
    activity: str
    timeout_s: float = 30.0
    max_result_chars: int = 12_000
    roles: frozenset[str] = ALL_ROLES
    submits_jobs: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def mutation(self) -> bool:
        return self.semantics in ("create", "compute")

    def activity_for(self, args: dict[str, Any]) -> str:
        try:
            return self.activity.format(**{k: v for k, v in args.items() if v is not None})
        except (KeyError, IndexError, ValueError):
            return self.activity.split("{")[0].strip() or self.name

    def openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "strict": True,
            "parameters": strict_schema(self.args),
        }


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"duplicate tool {spec.name}")
    REGISTRY[spec.name] = spec
    return spec


def tool(
    name: str,
    *,
    args: type[ToolArgs],
    semantics: Semantics,
    activity: str,
    timeout_s: float = 30.0,
    max_result_chars: int = 12_000,
    roles: frozenset[str] = ALL_ROLES,
    submits_jobs: bool = False,
) -> Callable[[Handler], Handler]:
    """Decorator: the handler's docstring is the model-facing description."""

    def deco(fn: Handler) -> Handler:
        desc = " ".join((fn.__doc__ or name).split())
        register(
            ToolSpec(
                name=name,
                description=desc,
                args=args,
                semantics=semantics,
                handler=fn,
                activity=activity,
                timeout_s=timeout_s,
                max_result_chars=max_result_chars,
                roles=roles,
                submits_jobs=submits_jobs,
            )
        )
        return fn

    return deco


# ------------------------------------------------------------------ strict schemas

_DROP = {
    "title",
    "default",
    "examples",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minItems",
    "maxItems",
    "uniqueItems",
    "multipleOf",
    "discriminator",
    "const",
}


def _inline(node: Any, defs: dict[str, Any], *, names: bool = False) -> Any:
    """Resolve $refs and drop unsupported keywords. ``names``: the dict maps property names (a field
    called e.g. ``title`` or ``format`` is a property, not a JSON-schema keyword, and is kept)."""
    if isinstance(node, dict):
        if names:
            return {k: _inline(v, defs) for k, v in node.items()}
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            merged = copy.deepcopy(defs[name])
            extra = {k: v for k, v in node.items() if k != "$ref"}
            merged.update(extra)
            return _inline(merged, defs)
        out = {}
        for k, v in node.items():
            if k == "$defs":
                continue
            if k == "properties":
                out[k] = _inline(v, defs, names=True)
                continue
            if k == "const":  # strict mode: represent a constant as a one-value enum
                out["enum"] = [v]
                continue
            if k in _DROP:
                continue
            out[k] = _inline(v, defs)
        return out
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        node = {k: _strictify(v) for k, v in node.items()}
        if "allOf" in node and len(node["allOf"]) == 1:
            inner = node.pop("allOf")[0]
            node = {**inner, **node}
        if node.get("type") == "object" or "properties" in node:
            props = node.get("properties", {})
            node["type"] = "object"
            node["properties"] = props
            node["required"] = list(props.keys())
            node["additionalProperties"] = False
        # flatten anyOf [X, null] where X is a simple type into type list
        any_of = node.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2 and {"type": "null"} in any_of:
            other = next(x for x in any_of if x != {"type": "null"})
            if set(other) <= {"type", "enum", "description"} and isinstance(other.get("type"), str):
                node.pop("anyOf")
                node["type"] = [other["type"], "null"]
                if "enum" in other:
                    node["enum"] = [*other["enum"], None]
            elif set(other) <= {"type", "items", "description"} and other.get("type") == "array":
                node.pop("anyOf")
                node["type"] = ["array", "null"]
                node["items"] = other["items"]
        return node
    if isinstance(node, list):
        return [_strictify(v) for v in node]
    return node


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Provider-subset strict schema: every property required, nullables typed, no extras."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    schema = _strictify(_inline(raw, defs))
    schema.pop("description", None)
    return schema


def check_strict(schema: Any, path: str = "$") -> list[str]:
    """Return violations of the strict subset (used by tests and the schema smoke check)."""
    errs: list[str] = []
    if isinstance(schema, dict):
        if "$ref" in schema or "$defs" in schema:
            errs.append(f"{path}: unresolved reference")
        for bad in _DROP & set(schema):
            if bad != "const":
                errs.append(f"{path}: unsupported keyword {bad}")
        if schema.get("type") == "object" or (
            isinstance(schema.get("type"), list) and "object" in schema["type"]
        ):
            props = schema.get("properties", {})
            if schema.get("additionalProperties") is not False:
                errs.append(f"{path}: additionalProperties must be false")
            if sorted(schema.get("required", [])) != sorted(props):
                errs.append(f"{path}: every property must be required")
        for k, v in schema.items():
            if k == "properties" and isinstance(v, dict):  # keys are property names, not keywords
                for name, sub in v.items():
                    errs.extend(check_strict(sub, f"{path}.properties.{name}"))
                continue
            errs.extend(check_strict(v, f"{path}.{k}"))
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            errs.extend(check_strict(v, f"{path}[{i}]"))
    return errs


def tools_for_role(role: str) -> list[ToolSpec]:
    _ensure_loaded()
    return [t for t in REGISTRY.values() if role in t.roles]


def openai_tools(role: str, extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    return [t.openai_tool() for t in tools_for_role(role)] + list(extra or [])


def tool_schema_version() -> str:
    """Hash of the exact tool set the provider sees (audit log, eval pinning)."""
    _ensure_loaded()
    from aabflow.copilot.answer_validation import FINAL_ANSWER_TOOL

    defs = [t.openai_tool() for t in sorted(REGISTRY.values(), key=lambda t: t.name)]
    defs.append(FINAL_ANSWER_TOOL)
    return "tools-" + content_hash(json.loads(json.dumps(defs)))[:16]


def _ensure_loaded() -> None:
    import aabflow.copilot.tools.compute
    import aabflow.copilot.tools.insight
    import aabflow.copilot.tools.read
    import aabflow.copilot.tools.view  # noqa: F401
