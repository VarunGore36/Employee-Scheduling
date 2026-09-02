"""HTTP shell over the service layer, on the standard library alone."""

from __future__ import annotations

import json
import secrets
import socket
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import service
from .generate import small_instance, university_instance
from .ruleinfo import catalog

MAX_BODY_BYTES = 8 * 1024 * 1024
DEFAULT_PORT = 8000
HEAVY_ROUTES = ("/solve", "/repair")
LOOPBACK = {"", "127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}
READ_ROUTES = ("/health", "/schema", "/rules", "/sample")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
}

@dataclass
class ApiConfig:
    """Server settings: everything a request needs but does not own."""

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    token: str = ""
    cors_origin: str = ""
    ui_dir: Path | None = None
    max_body: int = MAX_BODY_BYTES
    max_concurrent: int = 2
    socket_timeout: float = 60.0
    quiet: bool = False


def is_loopback(host: str) -> bool:
    return host.strip("[]").lower() in LOOPBACK


def sample_instance(start: str = "2026-09-12", days: int = 31, employees: int = 44,
                    seed: int = 7, small: bool = False):
    """An instance for the questionnaire to open with, so the UI has real options."""
    if small:
        return small_instance(seed=seed)
    if not 1 <= days <= 62:
        raise service.ServiceError("days must be between 1 and 62", "days")
    if not 1 <= employees <= 500:
        raise service.ServiceError("employees must be between 1 and 500", "employees")
    return university_instance(start=start, num_days=days, num_employees=employees,
                               seed=seed)


def query_kwargs(query: dict[str, list[str]]) -> dict:
    """Query string to sample_instance keywords; blanks fall back to the defaults."""
    kwargs: dict = {}
    for name, cast in (("start", str), ("days", int), ("employees", int), ("seed", int)):
        raw = (query.get(name) or [""])[0]
        if not raw:
            continue
        try:
            kwargs[name] = cast(raw)
        except ValueError as exc:
            raise service.ServiceError(f"{name} must be {cast.__name__}", name) from exc
    if query.get("small"):
        kwargs["small"] = True
    return kwargs


def make_handler(config: ApiConfig) -> type[BaseHTTPRequestHandler]:
    """One handler class bound to one configuration."""
    gate = threading.BoundedSemaphore(max(1, config.max_concurrent))
    started = time.time()

    class Handler(BaseHTTPRequestHandler):
        """Routes requests to service.handle and shapes every failure as JSON."""

        server_version = "roster"
        sys_version = ""
        protocol_version = "HTTP/1.1"
        timeout = config.socket_timeout

        def do_GET(self):
            self._route("GET")

        def do_HEAD(self):
            self._route("HEAD")

        def do_POST(self):
            self._route("POST")

        def do_OPTIONS(self):
            self._send(204, b"", "")

        def _route(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if not self._authorised(path):
                self._error(401, "authorisation required")
                return
            try:
                if method == "POST" and self._content_length() > config.max_body:
                    self.close_connection = True
                    self._error(413, f"request body over {config.max_body} bytes")
                    return
                self._handle(method, path, parse_qs(parsed.query))
            except service.ServiceError as exc:
                self._json(400, exc.to_dict())
            except (ValueError, KeyError, TypeError) as exc:
                self._json(400, {"error": str(exc), "field": ""})
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except (TimeoutError, socket.timeout):
                self.close_connection = True
                self._error(408, "the request body did not arrive in time")
            except Exception:
                traceback.print_exc(file=sys.stderr)
                self._json(500, {"error": "internal error", "field": ""})

        def _handle(self, method: str, path: str, query: dict) -> None:
            if method in ("GET", "HEAD"):
                if path == "/health":
                    self._json(200, {
                        "status": "ok",
                        "uptime_seconds": round(time.time() - started, 1),
                        "rule_types": len(service.REGISTRY),
                        "endpoints": sorted(service.ENDPOINTS),
                        "authenticated": bool(config.token),
                    })
                elif path == "/schema":
                    self._json(200, service.schema_payload({}))
                elif path == "/rules":
                    entries = catalog()
                    self._json(200, {"rule_types": entries, "count": len(entries)})
                elif path == "/sample":
                    inst = sample_instance(**query_kwargs(query))
                    self._json(200, {"instance": inst.to_dict()})
                elif path[1:] in service.ENDPOINTS:
                    self._allow_only(path, "POST")
                else:
                    self._static(path)
                return
            if method != "POST":
                self._error(405, f"{method} is not allowed here")
                return
            name = path[1:]
            if name not in service.ENDPOINTS:
                self._error(404, f"no route for POST {path}; try "
                                 f"{sorted('/' + n for n in service.ENDPOINTS)}")
                return
            payload = self._body()
            if path in HEAVY_ROUTES:
                self._guarded(name, payload)
            else:
                self._json(200, service.handle(name, payload))

        def _guarded(self, name: str, payload: dict) -> None:
            """A search owns a core for its whole budget, so queueing is refused openly."""
            if not gate.acquire(blocking=False):
                self._json(429, {"error": "already running the most searches this server "
                                          "allows; retry shortly", "field": ""},
                           extra={"Retry-After": "5"})
                return
            try:
                self._json(200, service.handle(name, payload))
            finally:
                gate.release()

        def _authorised(self, path: str) -> bool:
            """Health stays open for a supervisor to poll; the rest needs the token."""
            if not config.token or path == "/health":
                return True
            given = self.headers.get("X-Roster-Token", "")
            header = self.headers.get("Authorization", "")
            if header[:7].lower() == "bearer ":
                given = header[7:].strip()
            return secrets.compare_digest(given, config.token)

        def _content_length(self) -> int:
            raw = self.headers.get("Content-Length")
            if raw is None:
                if self.headers.get("Transfer-Encoding"):
                    raise service.ServiceError("send a body with Content-Length, not chunked")
                return 0
            try:
                size = int(raw)
            except ValueError as exc:
                raise service.ServiceError("Content-Length is not a number") from exc
            if size < 0:
                raise service.ServiceError("Content-Length is negative")
            return size

        def _body(self) -> dict:
            size = self._content_length()
            if not size:
                return {}
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise service.ServiceError("request body ended early")
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise service.ServiceError(f"body is not valid JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise service.ServiceError("request body must be a JSON object")
            return data

        def _static(self, path: str) -> None:
            """Serve the questionnaire page, and only from inside the ui folder."""
            if not config.ui_dir:
                if path == "/":
                    self._json(200, {"service": "roster",
                                     "get": list(READ_ROUTES),
                                     "post": sorted("/" + n for n in service.ENDPOINTS)})
                else:
                    self._error(404, f"no route for GET {path}")
                return
            root = config.ui_dir.resolve()
            target = (root / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if target != root and root not in target.parents:
                self._error(403, "outside the ui folder")
                return
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                self._error(404, f"no such file: {path}")
                return
            ctype = CONTENT_TYPES.get(target.suffix.lower())
            if ctype is None:
                self._error(415, f"will not serve {target.suffix or 'extensionless'} files")
                return
            self._send(200, target.read_bytes(), ctype)

        def _json(self, status: int, payload: dict, extra: dict | None = None) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"),
                       "application/json", extra)

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"error": message, "field": ""})

        def _allow_only(self, path: str, methods: str) -> None:
            self._json(405, {"error": f"{self.command} {path} is not allowed; use {methods}",
                             "field": ""}, extra={"Allow": methods})

        def _send(self, status: int, body: bytes, ctype: str,
                  extra: dict | None = None) -> None:
            self.send_response(status)
            if ctype:
                self.send_header("Content-Type", ctype)
            if status not in (204, 304):
                self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors()
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if body and self.command != "HEAD" and status not in (204, 304):
                self.wfile.write(body)

        def _cors(self) -> None:
            if not config.cors_origin:
                return
            self.send_header("Access-Control-Allow-Origin", config.cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization, X-Roster-Token")
            self.send_header("Access-Control-Max-Age", "600")

        def log_message(self, fmt: str, *args) -> None:
            if not config.quiet:
                sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    return Handler


def make_server(config: ApiConfig) -> ThreadingHTTPServer:
    """A bound but unstarted server; port 0 lets the OS choose one."""
    server = ThreadingHTTPServer((config.host, config.port), make_handler(config))
    server.daemon_threads = True
    return server


def serve(config: ApiConfig, insecure: bool = False) -> int:
    """Run until interrupted. Refuses a public bind with no token behind it."""
    if not is_loopback(config.host) and not config.token and not insecure:
        raise SystemExit(
            f"refusing to listen on {config.host} with no token: every endpoint would "
            "be open to anyone who can reach this machine, and a solve costs real cpu. "
            "Pass --token, or --insecure if you know the network is closed.")
    server = make_server(config)
    host, port = server.server_address[:2]
    print(f"roster api on http://{host}:{port}", file=sys.stderr)
    if not config.token:
        print("no token: anything that can reach this port can run a solve", file=sys.stderr)
    if config.ui_dir:
        print(f"ui from {config.ui_dir}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    finally:
        server.server_close()
    return 0

