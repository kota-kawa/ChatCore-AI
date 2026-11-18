"""HTTP-only capability negotiation; persistence and Redis retain canonical UI parts."""

from __future__ import annotations

import json

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from services.structured_ui import project_ui_payload

_UI_PATHS = frozenset(
    {
        "/api/chat",
        "/api/chat_regenerate",
        "/api/chat_edit_and_regenerate",
        "/api/chat_switch_branch",
        "/api/get_chat_history",
        "/api/shared_chat_room",
        "/api/chat_generation_stream",
        "/api/chat_stop",
    }
)


class StructuredUiDeliveryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in _UI_PATHS:
            await self.app(scope, receive, send)
            return
        capable = Headers(scope=scope).get("X-ChatCore-UI-Version") == "1"
        content_type = ""
        pending = b""
        start: Message | None = None

        async def deliver(message: Message) -> None:
            nonlocal start, content_type, pending
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message["headers"])}
                headers = MutableHeaders(scope=message)
                headers.add_vary_header("X-ChatCore-UI-Version")
                content_type = headers.get("content-type", "")
                if not capable and "application/json" in content_type:
                    start = message
                else:
                    await send(message)
                return
            if message["type"] != "http.response.body" or capable:
                await send(message)
                return
            if "application/json" in content_type:
                pending += message.get("body", b"")
                if not message.get("more_body", False):
                    try:
                        data = project_ui_payload(json.loads(pending))
                        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
                    except ValueError, RecursionError:
                        body = pending
                    if start is not None:
                        MutableHeaders(scope=start)["content-length"] = str(len(body))
                        await send(start)
                    await send({**message, "body": body})
                return
            if "text/event-stream" in content_type:
                pending += message.get("body", b"")
                while b"\n\n" in pending:
                    frame, pending = pending.split(b"\n\n", 1)
                    lines = []
                    for line in frame.split(b"\n"):
                        if line.startswith(b"data: "):
                            try:
                                data = project_ui_payload(json.loads(line[6:]))
                                line = b"data: " + json.dumps(data, ensure_ascii=False).encode()
                            except ValueError, RecursionError:
                                pass
                        lines.append(line)
                    await send({"type": "http.response.body", "body": b"\n".join(lines) + b"\n\n", "more_body": True})
                if not message.get("more_body", False):
                    await send({**message, "body": pending})
                return
            await send(message)

        await self.app(scope, receive, deliver)
