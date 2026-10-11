"""Proxy request handler: default-deny forwarding with SSRF and redaction guards."""

from __future__ import annotations

import urllib.parse

import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from .errors import SecurityError
from .security import build_forward_headers, clean_proxy_path
from .state import BrokerState


def _deny(state: BrokerState, status: int, message: str, **audit) -> JSONResponse:
    state.audit.record(kind="proxy", decision="deny", status=status, **audit)
    return JSONResponse(status_code=status, content={"error": message})


async def handle_proxy(
    state: BrokerState, service: str, raw_path: str, request: Request
) -> Response:
    settings = state.settings
    method = request.method.upper()
    svc = state.policy.get_service(service)

    if svc is None:
        return _deny(
            state, 403, "service not allowed",
            service=service, method=method, path=raw_path, reason="unknown service",
        )

    try:
        clean = clean_proxy_path(raw_path)
    except SecurityError as exc:
        return _deny(
            state, 400, "invalid path",
            service=service, method=method, path=raw_path, reason=str(exc),
        )

    if not state.policy.is_allowed(svc, method, clean):
        return _deny(
            state, 403, "endpoint not allowed",
            service=service, method=method, path=clean, reason="not in allowlist",
        )

    if not state.rate_limiter.check(service, svc.rate_limit_per_minute, 60.0):
        return _deny(
            state, 429, "rate limit exceeded",
            service=service, method=method, path=clean, reason="rate limit",
        )

    body = await request.body()
    if len(body) > settings.max_request_bytes:
        return _deny(
            state, 413, "request body too large",
            service=service, method=method, path=clean, reason="request too large",
        )

    url = f"{svc.base_url}/{clean}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    # SSRF defence-in-depth: the resolved host must still be the service's host.
    if urllib.parse.urlparse(url).hostname != svc.host:
        return _deny(
            state, 400, "invalid target host",
            service=service, method=method, path=clean, reason="host mismatch",
        )

    headers = build_forward_headers(dict(request.headers), svc.forward_headers)
    # Inject the real credential server-side. The agent never supplies this.
    headers[svc.auth.header] = svc.auth.format.format(secret=state.secrets[svc.auth.secret])

    try:
        upstream = await state.http.request(
            method, url, headers=headers, content=body if body else None
        )
    except httpx.HTTPError:
        return _deny(
            state, 502, "upstream request failed",
            service=service, method=method, path=clean, reason="upstream error",
        )

    # Redirects are never followed (follow_redirects=False); a 3xx is blocked outright
    # so an upstream cannot bounce us to another host.
    if 300 <= upstream.status_code < 400:
        return _deny(
            state, 502, "upstream redirect blocked",
            service=service, method=method, path=clean, reason="redirect blocked",
        )

    cap = svc.max_response_bytes or settings.max_response_bytes
    content = upstream.content
    if len(content) > cap:
        return _deny(
            state, 502, "upstream response too large",
            service=service, method=method, path=clean, reason="response too large",
        )

    text = content.decode("utf-8", errors="replace")
    redacted = state.redactor.redact(text)
    content_type = state.redactor.redact(
        upstream.headers.get("content-type", "application/octet-stream")
    )

    state.audit.record(
        kind="proxy", decision="allow", status=upstream.status_code,
        service=service, method=method, path=clean,
    )
    return Response(
        content=redacted.encode("utf-8"),
        status_code=upstream.status_code,
        headers={"content-type": content_type},
    )
