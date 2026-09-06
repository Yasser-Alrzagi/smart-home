"""Bounded request buffering, including chunked bodies, before multipart parsing.

At most the configured upload limit + small form overhead is retained. Deployment
still needs connection/concurrency limits; this is not an unlimited-load guarantee.
"""

from starlette.responses import JSONResponse
from app.core.config import settings


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        upload = scope["method"] == "POST" and scope["path"].endswith("/documents")
        limit = settings.DOCUMENT_MAX_BYTES + 65536 if upload else 65536
        headers = dict(scope.get("headers", []))

        async def reject(code, message):
            return await JSONResponse(
                {"detail": message},
                status_code=code,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)

        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await reject(400, "Invalid Content-Length")
        if length < 0 or length > limit:
            return await reject(413, "Request body is too large")
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            data = message.get("body", b"")
            size += len(data)
            if size > limit:
                return await reject(413, "Request body is too large")
            chunks.append(data)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
