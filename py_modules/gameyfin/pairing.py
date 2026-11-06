"""Phone pairing: a short-lived LAN web page for pasting the API token.

Typing an ~87-character token with the Deck's on-screen keyboard is painful, so the
Deck shows a QR code / short URL like ``http://192.168.1.20:41234/K7QX2M``. The
phone opens it, follows a link to Gameyfin's /settings/tokens, creates a token and
pastes it back. We validate it against the server before saving.

Guard rails: the server only runs while the pairing screen is open (and at most
TTL seconds), the path must carry a random one-time code, it stops after one
success or too many wrong-code requests, and request bodies are capped.
The page is plain HTTP on the LAN, like a typical Gameyfin install itself.
"""

from __future__ import annotations

import html
import json
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LEN = 6
TTL = 10 * 60
MAX_BAD_REQUESTS = 30
MAX_BODY = 8 * 1024

# (server_url, token) -> message on success; raise to reject (message shown on the phone).
Submit = Callable[[str, str], str]


def lan_ip(hint_host: str | None = None) -> str:
    """The Deck's address on the interface that routes to the Gameyfin server (or the internet)."""
    for host in filter(None, (hint_host, "192.168.0.1", "8.8.8.8")):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((host, 80))  # UDP: no packets sent
                ip = s.getsockname()[0]
                if not ip.startswith("127."):
                    return ip
        except OSError:
            continue
    return "127.0.0.1"


class PairingSession:
    def __init__(self, server_url: str, submit: Submit):
        self.server_url = server_url
        self.submit = submit
        self.code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        self.state = "waiting"  # waiting | done | expired | stopped | locked
        self.message = ""
        self.bad = 0
        self.expires_at = time.time() + TTL
        self._lock = threading.Lock()
        hint = urllib.parse.urlparse(server_url).hostname if server_url else None
        self.ip = lan_ip(hint)
        self.httpd = ThreadingHTTPServer(("0.0.0.0", 0), self._handler())
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="gameyfin-pairing", daemon=True)
        self._timer = threading.Timer(TTL, self.stop, kwargs={"state": "expired"})
        self._timer.daemon = True

    @property
    def url(self) -> str:
        return f"http://{self.ip}:{self.port}/{self.code}"

    def start(self) -> "PairingSession":
        self._thread.start()
        self._timer.start()
        return self

    def stop(self, state: str = "stopped") -> None:
        with self._lock:
            if self.state == "waiting":
                self.state = state
        self._timer.cancel()
        # shutdown() blocks until serve_forever returns; never call it on the server thread.
        threading.Thread(target=self._close, daemon=True).start()

    def _close(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except OSError:
            pass

    def status(self) -> dict:
        return {"state": self.state, "url": self.url, "code": self.code, "message": self.message,
                "expires_in": max(0, int(self.expires_at - time.time()))}

    # ---- HTTP ------------------------------------------------------------------

    def _handler(self):
        session = self

        class H(BaseHTTPRequestHandler):
            server_version = "gameyfin-decky-pairing"

            def log_message(self, *a):
                pass

            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, obj: dict) -> None:
                self._send(status, json.dumps(obj).encode(), "application/json")

            def _authorized(self) -> bool:
                path = self.path.split("?", 1)[0].strip("/").upper()
                if session.state != "waiting":
                    self._send(410, _closed_page(session.state).encode(), "text/html; charset=utf-8")
                    return False
                if not secrets.compare_digest(path, session.code):
                    session.bad += 1
                    if session.bad >= MAX_BAD_REQUESTS:
                        session.stop(state="locked")
                    self._send(404, b"Not found", "text/plain")
                    return False
                return True

            def do_GET(self):  # noqa: N802
                if self._authorized():
                    self._send(200, _page(session.server_url).encode(), "text/html; charset=utf-8")

            def do_POST(self):  # noqa: N802
                if not self._authorized():
                    return
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if n <= 0 or n > MAX_BODY:
                        raise ValueError("bad length")
                    data = json.loads(self.rfile.read(n))
                    server_url = str(data.get("server_url") or "").strip()
                    token = str(data.get("token") or "").strip()
                except (ValueError, AttributeError):
                    return self._json(400, {"ok": False, "message": "Invalid request"})
                if not server_url or not token:
                    return self._json(400, {"ok": False, "message": "Server URL and token are both required"})
                try:
                    msg = session.submit(server_url, token)
                except Exception as e:  # noqa: BLE001 — shown to the user on the phone
                    return self._json(200, {"ok": False, "message": str(e)})
                with session._lock:
                    session.state, session.message = "done", msg
                self._json(200, {"ok": True, "message": msg})
                session.stop(state="done")

        return H


def _closed_page(state: str) -> str:
    text = {"done": "Your Deck is paired. You can close this page.",
            "expired": "This pairing link expired. Start pairing again on the Deck."}.get(
        state, "Pairing is closed. Start pairing again on the Deck.")
    return _shell(f"<p>{html.escape(text)}</p>")


def _shell(body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Pair Gameyfin with your Deck</title>
<style>
:root {{ color-scheme: dark; }}
body {{ margin: 0; font: 16px/1.45 system-ui, sans-serif; background: #0e141b; color: #dcdedf; }}
main {{ max-width: 520px; margin: 0 auto; padding: 24px 16px 48px; }}
h1 {{ font-size: 22px; margin: 0 0 6px; }}
p, li {{ color: #b8bcbf; }}
ol {{ padding-left: 20px; }}
label {{ display: block; font-size: 14px; margin: 18px 0 6px; color: #dcdedf; }}
input, textarea {{ box-sizing: border-box; width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #3d4450;
  background: #1b2330; color: #fff; font: 15px ui-monospace, monospace; }}
textarea {{ height: 96px; resize: vertical; word-break: break-all; }}
a.btn, button {{ display: block; box-sizing: border-box; width: 100%; text-align: center; padding: 14px; margin-top: 12px;
  border-radius: 8px; border: 0; font: 600 16px system-ui, sans-serif; text-decoration: none; }}
a.btn {{ background: #2a3442; color: #fff; }}
button {{ background: #1a9fff; color: #fff; }}
button:disabled {{ opacity: .6; }}
#msg {{ margin-top: 16px; padding: 12px; border-radius: 8px; display: none; }}
#msg.ok {{ display: block; background: #12361f; color: #8ff0a4; }}
#msg.err {{ display: block; background: #3a1616; color: #ff9b9b; }}
</style></head><body><main>{body}</main></body></html>"""


def _page(server_url: str) -> str:
    body = f"""
<h1>Pair Gameyfin with your Deck</h1>
<ol>
  <li>Open Gameyfin and create a <b>personal access token</b>.</li>
  <li>Copy it, paste it below and press <b>Send to Deck</b>.</li>
</ol>
<label for="url">Gameyfin server</label>
<input id="url" type="url" inputmode="url" autocomplete="off" placeholder="http://192.168.1.10:8080"
  value="{html.escape(server_url)}">
<a class="btn" id="open" target="_blank" rel="noopener noreferrer">Open Gameyfin token page</a>
<label for="token">Personal access token</label>
<textarea id="token" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="gf_pat_…"></textarea>
<button id="send">Send to Deck</button>
<div id="msg"></div>
<script>
const $ = (id) => document.getElementById(id);
const tokenPage = () => $("url").value.trim().replace(/\\/+$/, "") + "/settings/tokens";
const syncLink = () => {{ $("open").href = tokenPage(); }};
$("url").addEventListener("input", syncLink); syncLink();
$("send").addEventListener("click", async () => {{
  const msg = $("msg"); msg.className = ""; $("send").disabled = true;
  try {{
    const r = await fetch(location.pathname, {{ method: "POST", headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ server_url: $("url").value.trim(), token: $("token").value.trim() }}) }});
    const d = await r.json().catch(() => ({{ ok: false, message: "Pairing is closed. Start again on the Deck." }}));
    msg.textContent = d.ok ? d.message + " You can close this page." : d.message;
    msg.className = d.ok ? "ok" : "err";
    if (d.ok) {{ $("token").value = ""; return; }}
  }} catch (e) {{
    msg.textContent = "Couldn't reach the Deck. Is the pairing screen still open?"; msg.className = "err";
  }}
  $("send").disabled = false;
}});
</script>"""
    return _shell(body)
