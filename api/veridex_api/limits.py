"""App-level request-body size guard.

The per-endpoint upload caps in sbr.py run AFTER ``await file.read()`` has already buffered the
whole body, and Starlette spools unbounded file parts to disk during receive, so an
unauthenticated POST to the public recovery endpoints could exhaust disk or RAM before the cap is
ever consulted. This middleware enforces a single global ceiling BEFORE the body is materialized:
it rejects a declared Content-Length over the cap, and accumulates streamed bytes to stop a
chunked body that lies about (or omits) its length. The client gets a clean 413, and the
per-endpoint caps remain as a second line of defense.
"""

from __future__ import annotations

import os

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Above the 25 MiB per-asset cap so a legitimate multipart upload (with its part overhead) still
# passes, while a multi-hundred-MB body is refused before it is read. Override with
# VERIDEX_MAX_REQUEST_BYTES.
DEFAULT_MAX_REQUEST_BYTES = 32 * 1024 * 1024


def max_request_bytes() -> int:
    """The active body-size ceiling, from VERIDEX_MAX_REQUEST_BYTES (a positive int) or the default,
    read per request so the cap can be tuned via the environment without a code change."""
    raw = os.environ.get("VERIDEX_MAX_REQUEST_BYTES")
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return DEFAULT_MAX_REQUEST_BYTES
        if value > 0:
            return value
    return DEFAULT_MAX_REQUEST_BYTES


async def _send_413(send: Send) -> None:
    body = b'{"detail":"request body too large"}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class LimitRequestBodyMiddleware:
    """Reject an HTTP request whose body exceeds the cap before it is fully buffered.

    Pure ASGI (not BaseHTTPMiddleware, which would read the whole body first). When a streamed body
    crosses the cap it stops feeding the app (returns http.disconnect), suppresses whatever the app
    would have answered from the truncated read, and sends a clean 413 itself, so the response is
    413 regardless of how the downstream route reacts (FastAPI, for instance, turns a body-read
    error on a JSON route into a 400, which this would otherwise surface instead of 413).
    """

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self._max_bytes = max_bytes

    @property
    def max_bytes(self) -> int:
        return self._max_bytes if self._max_bytes is not None else max_request_bytes()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.max_bytes

        # Fast path: an honest large upload declares Content-Length; reject before reading a byte.
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break
                if declared > limit:
                    await _send_413(send)
                    return
                break

        total = 0
        over_cap = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal total, over_cap
            if over_cap:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    over_cap = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if over_cap:
                # Suppress whatever the app produced from the truncated read; we answer with 413.
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)
        if over_cap and not response_started:
            await _send_413(send)
