"""Polite HTTP client: retries, throttling, cancellation, streaming size monitoring. Standard library only."""
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "GeoProjectStudio/0.2 (student GIS tool; polite client; contact: local user)"
MIN_INTERVAL = float(os.environ.get("GPS_MIN_INTERVAL", "0.25"))

# TEST ONLY: lets the offline test-suite redirect real hosts to a local mock server.
# Never set in normal use. Example: {"https://api.gbif.org": "http://127.0.0.1:9000/api.gbif.org"}
_OVERRIDES = json.loads(os.environ.get("GPS_TEST_HOST_OVERRIDES", "{}"))

_last_call = {}
_lock = threading.Lock()


class NetError(Exception):
    def __init__(self, msg, status=None, url=None):
        super().__init__(msg)
        self.status = status
        self.url = url


class Cancelled(Exception):
    pass


class SizeExceeded(Exception):
    """A single file grew past the per-file limit (checked from Content-Length up front, then while streaming)."""

    def __init__(self, size, limit, known_in_advance=False):
        super().__init__(f"file reached {size / 1e6:.1f} MB, over the {limit / 1e6:.0f} MB per-file limit")
        self.size = size
        self.limit = limit
        self.known_in_advance = known_in_advance


def _rewrite(url):
    for real, fake in _OVERRIDES.items():
        if url.startswith(real):
            return fake + url[len(real):]
    return url


def build_url(url, params=None):
    if params:
        q = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None},
            doseq=True, quote_via=urllib.parse.quote, safe=",()")
        url = url + ("&" if "?" in url else "?") + q
    return url


def _throttle(host):
    with _lock:
        now = time.time()
        wait = _last_call.get(host, 0) + MIN_INTERVAL - now
        _last_call[host] = max(now, _last_call.get(host, 0) + MIN_INTERVAL)
    if wait > 0:
        time.sleep(wait)


def _sleep(seconds, cancel):
    """Sleep in short steps so a cancel (or a superseded attempt) takes effect quickly."""
    end = time.time() + seconds
    while time.time() < end:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        time.sleep(min(0.25, end - time.time()))


def request(url, params=None, headers=None, timeout=60, retries=3, cancel=None, method="GET",
            max_bytes=None, on_bytes=None):
    """Return (status, headers_dict, body_bytes).

    Retries 429/5xx/timeouts with backoff. `max_bytes` aborts (SizeExceeded) as soon as Content-Length or the bytes
    actually received pass the limit. `on_bytes(n)` is called as data arrives (a heartbeat for progress/stall tracking).
    """
    full = build_url(url, params)
    real_host = urllib.parse.urlparse(full).netloc
    target = _rewrite(full)
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    hdrs.update(headers or {})
    last_err = None
    for attempt in range(retries + 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        _throttle(real_host)
        try:
            req = urllib.request.Request(target, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                h = dict(resp.headers)
                cl = h.get("Content-Length")
                if max_bytes and cl and cl.isdigit() and int(cl) > max_bytes:
                    raise SizeExceeded(int(cl), max_bytes, known_in_advance=True)
                if method == "HEAD":
                    return resp.status, h, b""
                chunks, n = [], 0
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    b = resp.read(65536)
                    if not b:
                        break
                    chunks.append(b)
                    n += len(b)
                    if on_bytes:
                        on_bytes(n)
                    if max_bytes and n > max_bytes:
                        raise SizeExceeded(n, max_bytes)
                return resp.status, h, b"".join(chunks)
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:  # noqa: BLE001
                pass
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                delay = 2 ** attempt
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.isdigit():
                    delay = min(int(ra), 30)
                _sleep(delay, cancel)
                last_err = NetError(f"HTTP {e.code}", e.code, full)
                continue
            raise NetError(f"HTTP {e.code} {e.reason}: {body[:200]!r}", e.code, full)
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, OSError) as e:
            last_err = NetError(f"Network error: {e}", None, full)
            if attempt < retries:
                _sleep(2 ** attempt, cancel)
                continue
    raise last_err or NetError("Unknown network failure", None, full)


def get_json(url, params=None, headers=None, **kw):
    status, hdrs, body = request(url, params, headers, **kw)
    if not body:
        return status, None
    try:
        return status, json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        raise NetError(f"Response was not JSON ({e}); first bytes: {body[:120]!r}", status, url)
