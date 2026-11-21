"""Polite HTTP client: retries, throttling, cancellation. Standard library only."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "GeoProjectStudio/0.1 (student GIS tool; polite client; contact: local user)"
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


def request(url, params=None, headers=None, timeout=90, retries=3, cancel=None):
    """Return (status, headers_dict, body_bytes). Retries 429/5xx/timeouts with backoff."""
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
            req = urllib.request.Request(target, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                delay = 2 ** attempt
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.isdigit():
                    delay = min(int(ra), 30)
                time.sleep(delay)
                last_err = NetError(f"HTTP {e.code}", e.code, full)
                continue
            raise NetError(f"HTTP {e.code} {e.reason}: {body[:200]!r}", e.code, full)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = NetError(f"Network error: {e}", None, full)
            if attempt < retries:
                time.sleep(2 ** attempt)
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
