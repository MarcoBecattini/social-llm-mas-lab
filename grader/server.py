"""Grader service: runs BigCodeBench's `untrusted_check` on {solution, test, entry_point} and returns {status, details}.

Deployed as a Render Private Service (no public address). It holds no secrets, runs as an unprivileged user, and
each check runs in a separate process with the upstream resource limits and timeouts. Optional shared token in
GRADER_TOKEN (checked in the X-Grader-Token header when set)."""
import json
import os
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "grader-0.1.0-bcb-09dd993"
WORKERS = int(os.environ.get("GRADER_WORKERS", "2"))
MAX_BODY = 2 * 1024 * 1024
TOKEN = os.environ.get("GRADER_TOKEN", "")
STATE = {"busy": 0, "done": 0, "started": time.time()}
LOCK = threading.Lock()


def check(item):
    from bigcodebench_eval import untrusted_check
    started = time.monotonic()
    status, details = untrusted_check(item["solution"], item["test"], item["entry_point"],
                                      max_as_limit=30 * 1024, max_data_limit=30 * 1024, max_stack_limit=10,
                                      min_time_limit=float(item.get("min_time_limit", 1.0)), gt_time_limit=float(item.get("gt_time_limit", 20.0)))
    return {"status": status, "details": {k: str(v)[:4000] for k, v in details.items()}, "seconds": round(time.monotonic() - started, 3)}


POOL = None


def pool():
    global POOL
    if POOL is None:
        POOL = ProcessPoolExecutor(max_workers=WORKERS)
    return POOL


class Handler(BaseHTTPRequestHandler):
    server_version = VERSION

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _authorized(self):
        return not TOKEN or self.headers.get("X-Grader-Token", "") == TOKEN

    def do_GET(self):
        if self.path in ("/healthz", "/"):
            with LOCK:
                self._send(200, {"ok": True, "version": VERSION, "workers": WORKERS, "busy": STATE["busy"], "done": STATE["done"],
                                 "uptime_seconds": round(time.time() - STATE["started"])})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/grade":
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413, {"error": "body missing or too large"})
        try:
            item = json.loads(self.rfile.read(length))
            for k in ("solution", "test", "entry_point"):
                if not isinstance(item.get(k), str) or not item[k]:
                    raise ValueError(f"missing {k}")
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, {"error": str(e)})
        budget = 250.0                                    # upstream per-task timeout is 240 s (BIGCODEBENCH_TIMEOUT_PER_TASK)
        with LOCK:
            STATE["busy"] += 1
        try:
            result = pool().submit(check, item).result(timeout=budget)
            self._send(200, result)
        except FutureTimeout:
            self._send(200, {"status": "timeout", "details": {"grader": "worker timeout"}, "seconds": budget})
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"[:300]})
        finally:
            with LOCK:
                STATE["busy"] -= 1; STATE["done"] += 1

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s\n" % (self.address_string(), fmt % args)); sys.stdout.flush()


def main():
    port = int(os.environ.get("PORT", "10000"))
    pool()
    print(f"{VERSION} listening on {port} with {WORKERS} workers", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
