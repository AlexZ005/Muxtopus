#!/usr/bin/env python3
"""A FAKE Telegram Bot API, so no test ever talks to the real bot.

    python3 tests/fake_telegram.py DIR [--token TOKEN] [--me USERNAME]

Listens on 127.0.0.1 on a free port and writes it to DIR/port once it is
serving. Point TELEGRAM_API at http://127.0.0.1:<port>.

    DIR/calls.jsonl     one line per request: {"method", "token", "params", "at"}
    DIR/updates.jsonl   the SCRIPT: a test appends Update objects (update_id
                        optional -- assigned in order) and getUpdates serves
                        them. Read fresh on every call, so a test can add one
                        while the client is already waiting.
    DIR/confirmed       the highest update_id a client confirmed with offset=,
                        which is how the real API forgets updates.

Only TOKEN is a good token (default 111:GOOD); anything else is a 401 on
every method, as Telegram answers a bad one. sendMessage returns increasing
message_ids. Also answers the two other backends' shapes -- POST /<topic>
(ntfy) and POST /v2/pushes (pushbullet) -- so their paths are testable too.
Stdlib only.
"""
import json
import pathlib
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = pathlib.Path(sys.argv[1])
ARGS = sys.argv[2:]
TOKEN = ARGS[ARGS.index("--token") + 1] if "--token" in ARGS else "111:GOOD"
ME = ARGS[ARGS.index("--me") + 1] if "--me" in ARGS else "muxfake_bot"
LOCK = threading.Lock()
STATE = {"msg": 1000}


def record(method, token, params):
    with LOCK, open(DIR / "calls.jsonl", "a") as f:
        f.write(json.dumps({"method": method, "token": token, "params": params,
                            "at": time.time()}, ensure_ascii=False) + "\n")


def updates():
    out, n = [], 0
    try:
        for line in (DIR / "updates.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            n += 1
            u = json.loads(line)
            u.setdefault("update_id", n)
            out.append(u)
    except OSError:
        pass
    return out


def confirmed():
    try:
        return int((DIR / "confirmed").read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def params(self):
        u = urllib.parse.urlsplit(self.path)
        p = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = self.headers.get("Content-Type", "")
        if raw and not u.path.startswith(("/bot", "/v2/")):
            p["_body"] = raw.decode(errors="replace")      # ntfy: the body IS the message
        elif raw and "json" in ctype:
            p.update(json.loads(raw))
        elif raw and "form-urlencoded" in ctype:
            p.update({k: v[-1] for k, v in urllib.parse.parse_qs(raw.decode()).items()})
        elif raw:
            p["_body"] = raw.decode(errors="replace")
        return u.path, p

    def do_GET(self):
        self.handle_any()

    def do_POST(self):
        self.handle_any()

    def handle_any(self):
        path, p = self.params()
        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[0].startswith("bot"):
            token, method = parts[0][3:], parts[1]
            record(method, token, p)
            if token != TOKEN:
                return self.reply(401, {"ok": False, "error_code": 401,
                                        "description": "Unauthorized"})
            return self.bot(method, p)
        if path == "/v2/pushes":
            record("pushbullet", self.headers.get("Access-Token", ""), p)
            return self.reply(200, {"active": True})
        record("ntfy", path.strip("/"), {**p, "title": self.headers.get("Title", "")})
        return self.reply(200, {"id": "x"})

    def bot(self, method, p):
        if method == "getMe":
            return self.reply(200, {"ok": True, "result": {
                "id": 111, "is_bot": True, "first_name": "Mux Fake", "username": ME}})
        if method == "getUpdates":
            off = int(p.get("offset") or 0)
            with LOCK:
                if off and off - 1 > confirmed():
                    (DIR / "confirmed").write_text(str(off - 1))
                floor = confirmed()
            res = [u for u in updates() if u["update_id"] > floor]
            lim = int(p.get("limit") or 100)
            return self.reply(200, {"ok": True, "result": res[:lim]})
        if method in ("sendMessage", "editMessageText", "editMessageReplyMarkup"):
            chat = p.get("chat_id")
            if str(chat) == "403":
                return self.reply(403, {"ok": False, "error_code": 403,
                                        "description": "Forbidden: bot can't initiate conversation with a user"})
            with LOCK:
                if method == "sendMessage":
                    STATE["msg"] += 1
                    mid = STATE["msg"]
                else:
                    mid = int(p.get("message_id") or 0)
            return self.reply(200, {"ok": True, "result": {
                "message_id": mid, "chat": {"id": chat}, "text": p.get("text", "")}})
        if method == "answerCallbackQuery":
            return self.reply(200, {"ok": True, "result": True})
        return self.reply(404, {"ok": False, "error_code": 404, "description": "Not Found"})


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    tmp = DIR / "port.tmp"
    tmp.write_text(str(srv.server_address[1]))
    tmp.replace(DIR / "port")
    srv.serve_forever()


if __name__ == "__main__":
    main()
