"""Verify retry logic in _request_json using a local HTTP server (offline)."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from github_trending.fetcher import _request_json  # noqa: E402

state = {"hits": 0, "rate_hits": 0}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/flaky":
            state["hits"] += 1
            if state["hits"] < 3:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"boom")
            else:
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
        elif self.path == "/rate":
            state["rate_hits"] += 1
            if state["rate_hits"] == 1:
                self.send_response(403)
                self.send_header("X-RateLimit-Remaining", "0")
                self.send_header("X-RateLimit-Reset", str(int(__import__("time").time()) + 2))
                self.end_headers()
                self.wfile.write(b'{"message":"API rate limit exceeded"}')
            else:
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"nope")

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

try:
    # 1) 500, 500, 200 -> should succeed after 2 retries
    out = _request_json(f"http://127.0.0.1:{port}/flaky", timeout=5)
    assert out == {"ok": True}, out
    assert state["hits"] == 3
    print("retry-on-5xx OK (hits=3)")

    # 2) 403 rate limit -> waits, then succeeds on second attempt
    out = _request_json(f"http://127.0.0.1:{port}/rate", timeout=5)
    assert out == {"ok": True}, out
    assert state["rate_hits"] == 2
    print("rate-limit wait+retry OK (hits=2)")

    # 3) 404 raises GitHubError
    try:
        _request_json(f"http://127.0.0.1:{port}/missing", timeout=5)
        raise AssertionError("expected GitHubError")
    except Exception as exc:
        assert type(exc).__name__ == "GitHubError", type(exc).__name__
    print("404 -> GitHubError OK")
finally:
    server.shutdown()
