"""Lokal HTTP-server, byggd på standardbiblioteket.

Ingen Flask, inget pip install: verktyget ska gå att klona och köra. HTTP-lagret
är medvetet tunt — all logik ligger i ``api.py`` — så att det går att byta mot
Flask eller FastAPI utan att röra något annat.

Servern binder mot 127.0.0.1 och är inte avsedd att exponeras.
"""

from __future__ import annotations

import email
import json
import mimetypes
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .api import Api, ApiError
from .storage import Store

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


class Route:
    def __init__(self, method: str, pattern: str, handler: Callable) -> None:
        self.method = method
        self.regex = re.compile("^{}$".format(pattern))
        self.handler = handler


def build_routes(api: Api) -> List[Route]:
    return [
        Route("GET", r"/api/state", lambda req, m: api.state()),
        Route("GET", r"/api/transactions", lambda req, m: api.transactions()),
        Route("POST", r"/api/import/preview", _import_preview(api)),
        Route("POST", r"/api/import/commit", lambda req, m: api.import_commit(req.json().get("token", ""))),
        Route("POST", r"/api/import/cancel", lambda req, m: api.import_cancel(req.json().get("token", ""))),
        Route("PATCH", r"/api/transactions/bulk", lambda req, m: api.update_transactions_bulk(
            req.json().get("ids") or [], req.json().get("changes") or {}
        )),
        Route("PATCH", r"/api/transactions/(?P<id>.+)", lambda req, m: api.update_transaction(
            _unquote(m.group("id")), req.json()
        )),
        Route("POST", r"/api/sources", lambda req, m: api.create_source(req.json())),
        Route("POST", r"/api/sources/rematch", lambda req, m: api.rematch_sources()),
        Route("POST", r"/api/sources/test-pattern", lambda req, m: api.test_pattern(req.json())),
    ]


def _unquote(value: str) -> str:
    from urllib.parse import unquote

    return unquote(value)


def _import_preview(api: Api) -> Callable:
    def handler(request, match):
        parts = request.multipart()
        upload = parts.get("file")
        if not upload:
            raise ApiError("Ingen fil bifogades.")
        filename, data = upload
        profile_id = parts.get("profile_id")
        if isinstance(profile_id, tuple):
            profile_id = profile_id[1].decode("utf-8", "replace")
        return api.import_preview(filename, data, profile_id=profile_id or None)

    return handler


class Request:
    """Det lilla av HTTP som handlarna behöver."""

    def __init__(self, handler: "Handler") -> None:
        self.handler = handler
        self._body: Optional[bytes] = None

    def body(self) -> bytes:
        if self._body is None:
            length = int(self.handler.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD_BYTES:
                raise ApiError("Filen är för stor (max 32 MB).", status=413)
            self._body = self.handler.rfile.read(length) if length else b""
        return self._body

    def json(self) -> Dict[str, Any]:
        raw = self.body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ApiError("Ogiltig JSON i anropet.")
        return data if isinstance(data, dict) else {}

    def multipart(self) -> Dict[str, Any]:
        """Tolka multipart/form-data.

        Textfält returneras som strängar, filer som ``(filnamn, bytes)``.
        """
        content_type = self.handler.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ApiError("Förväntade multipart/form-data.")
        raw = (
            b"Content-Type: "
            + content_type.encode("utf-8")
            + b"\r\nMIME-Version: 1.0\r\n\r\n"
            + self.body()
        )
        message = email.message_from_bytes(raw)
        fields: Dict[str, Any] = {}
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                fields[name] = (filename, payload)
            else:
                charset = part.get_content_charset() or "utf-8"
                fields[name] = payload.decode(charset, "replace").strip()
        return fields


class Handler(BaseHTTPRequestHandler):
    server_version = "Kvittokoll"
    routes: List[Route] = []

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def _dispatch(self, method: str) -> None:
        path = urlparse(self.path).path
        for route in self.routes:
            if route.method != method:
                continue
            match = route.regex.match(path)
            if not match:
                continue
            try:
                payload = route.handler(Request(self), match)
            except ApiError as error:
                self._send_json({"error": error.message}, status=error.status)
            except Exception as error:  # ett fel i en rad ska inte fälla servern
                self.log_error("Ohanterat fel i %s %s: %s", method, path, error)
                self._send_json({"error": "Internt fel: {}".format(error)}, status=500)
            else:
                self._send_json(payload)
            return

        if method == "GET":
            self._serve_static(path)
            return
        self._send_json({"error": "Okänd väg: {}".format(path)}, status=404)

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR)
        except ValueError:
            self._send_json({"error": "Otillåten sökväg."}, status=403)
            return
        if not target.is_file():
            self._send_json({"error": "Hittades inte."}, status=404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        print("  {} {}".format(self.command or "", self.path or ""))


def create_server(store: Store, host: str = "127.0.0.1", port: int = 8420) -> ThreadingHTTPServer:
    api = Api(store)
    handler = type("BoundHandler", (Handler,), {"routes": build_routes(api)})
    return ThreadingHTTPServer((host, port), handler)


def serve(store: Store, host: str = "127.0.0.1", port: int = 8420, open_browser: bool = True) -> None:
    httpd = create_server(store, host, port)
    url = "http://{}:{}/".format(host, httpd.server_address[1])
    print("Kvittokoll kör på {}".format(url))
    print("Data i {}".format(store.data_dir))
    print("Avsluta med Ctrl+C.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStänger.")
    finally:
        httpd.server_close()
