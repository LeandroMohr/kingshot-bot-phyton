"""Local HTTP server for the bot control panel (stdlib only).

Binds to 127.0.0.1. ``app.py`` opens it inside a pywebview window (or the
browser with ``--browser``).
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import account_prefs
import config
from adb_controller import discover_devices
from gui import planning
from gui import settings_schema as schema
from gui.bot_manager import BotManager
from gui.i18n import L, UserError, localize, pick_lang

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}
MAX_BODY = 1024 * 1024  # the planning document is ~50 KB
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,253}$")
_ACCOUNT_RE = re.compile(r"^\d{1,20}$")

manager = BotManager()
_task_info: dict[str, dict] | None = None


def task_info() -> dict[str, dict]:
    global _task_info
    if _task_info is None:
        from tasks import TASKS  # heavy import (OpenCV/Tesseract), done once on demand
        _task_info = {t.name: {"loop": t.loop, "interval": t.interval} for t in TASKS}
    return _task_info


def menu_sections() -> list[dict]:
    """Schema sections enriched with each task's schedule; registered tasks the
    schema doesn't describe yet land in an "Other" section."""
    info = task_info()
    sections = []
    for section in schema.SECTIONS:
        tasks = [{**task, **info[task["task"]]} for task in section["tasks"]
                 if task["task"] in info]
        sections.append({**section, "tasks": tasks})
    described = {task["task"] for task in schema.iter_tasks()}
    extra = [{"task": name, "title": name, "summary": "", "fields": [], "howto": [],
              **meta} for name, meta in info.items() if name not in described]
    if extra:
        sections.append({"id": "other", "title": L("Other", "Outros"), "tasks": extra})
    return sections


def validate_prefs(changes: dict, lang: str) -> dict:
    if not isinstance(changes, dict):
        raise UserError("prefs_not_object")
    clean = {}
    for key, value in changes.items():
        if key == "disabled_tasks":
            if not isinstance(value, list) or not all(n in task_info() for n in value):
                raise UserError("invalid_task_list")
            clean[key] = sorted(set(value))
            continue
        field = schema.FIELDS.get(key)
        if field is None:
            raise UserError("unknown_pref", key=key)
        label = localize(field["label"], lang)
        if field["group"]:
            label = f"{localize(field['group']['label'], lang)} – {label}"
        if field["type"] == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise UserError("must_be_int", label=label)
            if not field["min"] <= value <= field["max"]:
                raise UserError("out_of_range", label=label, min=field["min"], max=field["max"])
        elif field["type"] == "choice" and value not in [c["value"] for c in field["choices"]]:
            raise UserError("invalid_choice", label=label)
        elif field["type"] == "bool" and not isinstance(value, bool):
            raise UserError("must_be_bool", label=label)
        clean[key] = value
    return clean


def parse_account(value) -> str:
    account_id = str(value or "")
    if not _ACCOUNT_RE.match(account_id):
        raise UserError("invalid_account")
    return account_id


def parse_port(value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise UserError("invalid_port") from None
    if not 1 <= port <= 65535:
        raise UserError("invalid_port")
    return port


class Handler(BaseHTTPRequestHandler):
    # -- responses ---------------------------------------------------------
    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel_path: str) -> None:
        if rel_path in ("", "/"):
            rel_path = "/index.html"
        file_path = (STATIC_DIR / rel_path.lstrip("/")).resolve()
        if STATIC_DIR not in file_path.parents or not file_path.is_file():
            self.send_error(404)
            return
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         CONTENT_TYPES.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")  # always pick up panel updates
        self.end_headers()
        self.wfile.write(body)

    def _host_allowed(self) -> bool:
        # Blocks DNS-rebinding: only accept requests addressed to localhost.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ALLOWED_HOSTS

    @property
    def lang(self) -> str:
        return pick_lang(self.headers.get("X-Lang"))

    def _send_error_text(self, status: int, exc: Exception) -> None:
        text = exc.text(self.lang) if isinstance(exc, UserError) else str(exc)
        self._send_json(status, {"error": text})

    def _read_json(self) -> dict:
        # Requiring JSON forces a CORS preflight, so other sites can't post here.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise UserError("content_type")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise UserError("body_too_large")
        data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise UserError("body_not_object")
        return data

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        if not self._host_allowed():
            self.send_error(403)
            return
        url = urlparse(self.path)
        query = parse_qs(url.query)
        try:
            if url.path == "/api/state":
                self._send_json(200, {
                    "sections": localize(menu_sections(), self.lang),
                    "general_howto": localize(schema.GENERAL_HOWTO, self.lang),
                    "bots": manager.list(),
                    "default_host": config.ADB_HOST,
                    "default_port": config.ADB_PORT,
                })
            elif url.path == "/api/devices":
                devices = []
                for serial in discover_devices(config.ADB_HOST):
                    host, _, port = serial.partition(":")
                    if port.isdigit():
                        devices.append({"serial": serial, "host": host, "port": int(port)})
                self._send_json(200, {"devices": devices})
            elif url.path == "/api/accounts":
                self._send_json(200, {"accounts": account_prefs.list_accounts()})
            elif url.path == "/api/planning":
                account_id = parse_account(query.get("account_id", [""])[0])
                self._send_json(200, {"planning": planning.load(account_id)})
            elif url.path == "/api/logs":
                bot = manager.get(parse_port(query.get("port", [""])[0]))
                if bot is None:
                    raise UserError("no_bot", port=query.get("port", [""])[0])
                since = int(query.get("since", ["0"])[0] or 0)
                lines, cursor = bot.logs_since(since)
                self._send_json(200, {"lines": lines, "cursor": cursor,
                                      "running": bot.running})
            else:
                self._send_static(url.path)
        except ValueError as exc:
            self._send_error_text(400, exc)
        except FileNotFoundError:
            self._send_error_text(500, UserError("adb_missing", binary=config.ADB_BINARY))
        except Exception as exc:  # noqa: BLE001 - surface the error in the UI
            self._send_json(500, {"error": str(exc)})

    def do_POST(self):
        if not self._host_allowed():
            self.send_error(403)
            return
        try:
            data = self._read_json()
            path = urlparse(self.path).path
            if path == "/api/bots/start":
                host = str(data.get("host") or config.ADB_HOST)
                if not _HOST_RE.match(host):
                    raise UserError("invalid_host")
                bot = manager.start(host, parse_port(data.get("port")))
                self._send_json(200, {"bot": bot.to_dict()})
            elif path == "/api/bots/stop":
                manager.stop(parse_port(data.get("port")))
                self._send_json(200, {"ok": True})
            elif path == "/api/bots/pause":
                manager.require(parse_port(data.get("port"))).pause()
                self._send_json(200, {"ok": True})
            elif path == "/api/bots/resume":
                manager.require(parse_port(data.get("port"))).resume()
                self._send_json(200, {"ok": True})
            elif path == "/api/accounts/prefs":
                account_id = parse_account(data.get("account_id"))
                account_prefs.update_prefs(account_id, validate_prefs(data.get("preferences"), self.lang))
                self._send_json(200, {"ok": True})
            elif path == "/api/planning":
                planning_data = data.get("planning")
                if not isinstance(planning_data, dict):
                    raise UserError("invalid_planning")
                planning.save(parse_account(data.get("account_id")), planning_data)
                self._send_json(200, {"ok": True})
            else:
                self._send_json(404, {"error": UserError("route_not_found").text(self.lang)})
        except ValueError as exc:
            self._send_error_text(400, exc)
        except Exception as exc:  # noqa: BLE001 - surface the error in the UI
            self._send_json(500, {"error": str(exc)})

    def log_message(self, format, *args):  # noqa: A002 - keep the console quiet
        pass


def make_server(port: int = 0) -> ThreadingHTTPServer:
    """Create the server on 127.0.0.1 (port 0 = any free port)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    return httpd
