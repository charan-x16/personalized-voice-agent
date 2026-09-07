from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    """Reject oversized request bodies while they are streamed into the app."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value for name, value in scope["headers"] if name.lower() == b"content-length"
        ]
        if content_lengths:
            try:
                declared_length = int(content_lengths[-1])
            except ValueError:
                await self._reject(scope, receive, send, status_code=400)
                return
            if declared_length < 0:
                await self._reject(scope, receive, send, status_code=400)
                return
            if declared_length > self.max_bytes:
                await self._reject(scope, receive, send, status_code=413)
                return

        received_bytes = 0
        buffered_messages: list[Message] = []
        while True:
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    await self._reject(scope, receive, send, status_code=413)
                    return
                buffered_messages.append(message)
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                buffered_messages.append(message)
                break

        message_index = 0

        async def replay_receive() -> Message:
            nonlocal message_index
            if message_index < len(buffered_messages):
                message = buffered_messages[message_index]
                message_index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
    ) -> None:
        detail = "Request body too large" if status_code == 413 else "Invalid Content-Length"
        response = JSONResponse({"detail": detail}, status_code=status_code)
        await response(scope, receive, send)
