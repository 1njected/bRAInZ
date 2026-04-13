"""API key authentication middleware."""

import os
import re
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def get_api_keys() -> set[str]:
    raw = os.environ.get("API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Pass preflight requests through so CORS middleware can handle them
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow health check without auth
        if request.url.path in ("/api/health", "/"):
            return await call_next(request)

        # Static files and snapshot assets (referenced by relative URLs inside iframes)
        if request.url.path.startswith("/static"):
            return await call_next(request)
        if re.search(r"^/api/items/[^/]+/assets/", request.url.path):
            return await call_next(request)

        api_keys = get_api_keys()
        if not api_keys:
            # No keys configured — open access (dev mode)
            return await call_next(request)

        # snapshot/original/image endpoints are loaded by <iframe>/<img> which cannot
        # send custom headers — allow ?key= query param only for these browser-navigated GETs
        key = request.headers.get("X-API-Key")
        if not key and request.method == "GET" and re.search(
            r"^/api/items/[^/]+/(snapshot|original)$", request.url.path
        ):
            key = request.query_params.get("key")

        if not key or key not in api_keys:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
