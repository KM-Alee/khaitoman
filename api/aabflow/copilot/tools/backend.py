"""In-process access to the /api/v2 contract for copilot tools.

Tools are thin wrappers: they call the same validated routes the UI uses (over an
ASGI transport, no network), so business validation, idempotency keys, typed
errors and job semantics are shared with the rest of the product.
"""

from __future__ import annotations

from typing import Any

import httpx

API = "/api/v2"


class ToolFailure(Exception):
    """A tool could not complete; returned to the model as a typed error, never as data."""

    def __init__(
        self, code: str, detail: str, *, status: int | None = None, extra: dict | None = None
    ):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status
        self.extra = extra or {}

    def as_output(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": False, "error": {"code": self.code, "detail": self.detail}}
        if self.extra:
            out["error"].update(self.extra)
        return out


class RouteUnavailable(ToolFailure):
    """The backing route is not installed in this build (capability missing, not a data error)."""


class Backend:
    def __init__(
        self, app: Any = None, *, client: httpx.AsyncClient | None = None, timeout_s: float = 60.0
    ):
        if client is None:
            if app is None:
                raise ValueError("Backend needs an app or a client")
            client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://aabflow.internal",
                timeout=timeout_s,
            )
        self.client = client

    async def aclose(self) -> None:
        await self.client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            r = await self.client.request(
                method, API + path, params=clean, json=json, headers=headers
            )
        except httpx.HTTPError as exc:  # transport failure inside the process
            raise ToolFailure("BACKEND_UNAVAILABLE", f"{method} {path} failed: {exc}") from exc
        try:
            body = r.json()
        except ValueError:
            body = {"detail": r.text[:500]}
        if r.status_code >= 400:
            code = body.get("code", "ERROR") if isinstance(body, dict) else "ERROR"
            detail = body.get("detail", "") if isinstance(body, dict) else str(body)
            if not isinstance(detail, str):
                detail = str(detail)[:800]
            if r.status_code == 404 and code == "NOT_FOUND" and detail.startswith(API + "/"):
                raise RouteUnavailable(
                    "CAPABILITY_UNAVAILABLE",
                    f"this build has no {method} {path.split('?')[0]} service yet",
                    status=404,
                )
            extra = (
                {k: v for k, v in body.items() if k not in ("code", "detail")}
                if isinstance(body, dict)
                else {}
            )
            raise ToolFailure(code, detail, status=r.status_code, extra=_trim(extra))
        return body

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Any = None, *, idempotency_key: str | None = None) -> Any:
        return await self.request("POST", path, json=json, idempotency_key=idempotency_key)

    async def get_asset(self, url: str) -> Any:
        """GET a JSON pilot asset served by the same app (``/assets/pilots/...``), never an external URL."""
        if not url.startswith("/assets/pilots/"):
            raise ToolFailure("INVALID_INPUT", "only local pilot assets can be read")
        try:
            r = await self.client.get(url)
        except httpx.HTTPError as exc:
            raise ToolFailure("BACKEND_UNAVAILABLE", f"GET {url} failed: {exc}") from exc
        if r.status_code >= 400:
            raise ToolFailure("NOT_FOUND", f"asset {url} is not available", status=r.status_code)
        return r.json()


def _trim(extra: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in extra.items():
        s = str(v)
        out[k] = v if len(s) <= 600 else s[:600] + "..."
    return out
