import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rate_limit: float = 5.0, capacity: float = 100.0):
        """
        rate_limit: float - tokens to add per second (default: 5.0 -> 300 requests/minute)
        capacity: float - max burst tokens (default: 100.0)
        """
        super().__init__(app)
        self.rate_limit = rate_limit
        self.capacity = capacity
        self.clients = {}

    async def dispatch(self, request: Request, call_next):
        # Allow checking health endpoint without consuming tokens
        if request.url.path in ("/", "/health", "/widget.js"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self.clients:
            self.clients[client_ip] = {"tokens": self.capacity, "last_update": now}

        client = self.clients[client_ip]
        elapsed = now - client["last_update"]
        
        # Refill
        client["tokens"] = min(self.capacity, client["tokens"] + elapsed * self.rate_limit)
        client["last_update"] = now

        if client["tokens"] >= 1.0:
            client["tokens"] -= 1.0
            return await call_next(request)
        else:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Rate limit exceeded."}
            )
