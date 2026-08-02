import time
import threading
from collections import defaultdict, deque
from functools import wraps

from flask import request, jsonify

_LOCK = threading.Lock()
_ATTEMPTS = defaultdict(deque)  # key -> deque[timestamps]


def _client_ip():
    # Trust X-Forwarded-For's first hop when present (typical behind
    # Railway/Fly/Vercel proxies), else fall back to the socket address.
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit(max_attempts=5, window_seconds=60, key_prefix="login"):
    """
    Simple in-memory sliding-window rate limiter, meant for login-style
    endpoints that would otherwise allow unlimited password guessing.

    NOTE: this is per-process. A single gunicorn worker is fine for a small
    self-hosted gateway, but if you scale to multiple workers/instances each
    keeps its own counter - for stronger guarantees at scale, swap this for
    a shared store (Redis) instead.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            key = f"{key_prefix}:{_client_ip()}"
            now = time.time()
            with _LOCK:
                bucket = _ATTEMPTS[key]
                while bucket and now - bucket[0] > window_seconds:
                    bucket.popleft()
                if len(bucket) >= max_attempts:
                    retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
                    response = jsonify({
                        "error": "Too many attempts. Please wait before trying again."
                    })
                    response.status_code = 429
                    response.headers["Retry-After"] = str(retry_after)
                    return response
                bucket.append(now)
            return fn(*args, **kwargs)
        return wrapped
    return decorator
