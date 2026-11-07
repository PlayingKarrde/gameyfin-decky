"""Phone form: a short-lived LAN web page where a phone sends secrets to the Deck.

Typing a long token on the Deck's on-screen keyboard is painful, and some sign-ins
(SteamGridDB's goes through Steam) need popups that Decky's browser blocks. So the
Deck shows a QR code / short URL like ``http://192.168.1.20:41234/K7QX2M``; the phone
opens it, fills in the plugin's form and posts it back.

The plugin supplies the page (``page()`` -> full HTML, usually ``shell(...)``) and
``submit(fields) -> message``, which validates and saves; raising rejects the post and
shows the exception text on the phone.

Guard rails: the server only runs while the pairing screen is open (and at most TTL
seconds), the path must carry a random one-time code, it stops after one success or
too many wrong-code requests, and request bodies are capped. Plain HTTP on the LAN.
"""

from __future__ import annotations

import html
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .sgdb import KEY_PAGE as SGDB_KEY_PAGE

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LEN = 6
TTL = 10 * 60
MAX_BAD_REQUESTS = 30
MAX_BODY = 8 * 1024

# Posted fields (all strings, stripped) -> message on success. Raise to reject.
Submit = Callable[[dict], str]


def lan_ip(hint_host: str | None = None) -> str:
    """The Deck's address on the interface that routes to the plugin's server (or the internet)."""
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


class PhoneForm:
    def __init__(self, page: Callable[[], str], submit: Submit, hint_host: str | None = None,
                 closed_title: str = "Pair with your Deck"):
        self.page = page
        self.submit = submit
        self.closed_title = closed_title
        self.code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        self.state = "waiting"  # waiting | done | expired | stopped | locked
        self.message = ""
        self.bad = 0
        self.expires_at = time.time() + TTL
        self._lock = threading.Lock()
        self.ip = lan_ip(hint_host)
        self.httpd = ThreadingHTTPServer(("0.0.0.0", 0), self._handler())
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="phone-form", daemon=True)
        self._timer = threading.Timer(TTL, self.stop, kwargs={"state": "expired"})
        self._timer.daemon = True

    @property
    def url(self) -> str:
        return f"http://{self.ip}:{self.port}/{self.code}"

    def start(self) -> "PhoneForm":
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
        form = self

        class H(BaseHTTPRequestHandler):
            server_version = "decky-phone-form"

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
                if form.state != "waiting":
                    self._send(410, closed_page(form.state, form.closed_title).encode(), "text/html; charset=utf-8")
                    return False
                if not secrets.compare_digest(path, form.code):
                    form.bad += 1
                    if form.bad >= MAX_BAD_REQUESTS:
                        form.stop(state="locked")
                    self._send(404, b"Not found", "text/plain")
                    return False
                return True

            def do_GET(self):  # noqa: N802
                if self._authorized():
                    self._send(200, form.page().encode(), "text/html; charset=utf-8")

            def do_POST(self):  # noqa: N802
                if not self._authorized():
                    return
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if n <= 0 or n > MAX_BODY:
                        raise ValueError("bad length")
                    data = json.loads(self.rfile.read(n))
                    if not isinstance(data, dict):
                        raise ValueError("not an object")
                    fields = {str(k): str(v if v is not None else "").strip() for k, v in data.items()}
                except (ValueError, AttributeError):
                    return self._json(400, {"ok": False, "message": "Invalid request"})
                try:
                    msg = form.submit(fields)
                except Exception as e:  # noqa: BLE001 — shown to the user on the phone
                    return self._json(200, {"ok": False, "message": str(e)})
                with form._lock:
                    form.state, form.message = "done", msg
                self._json(200, {"ok": True, "message": msg})
                form.stop(state="done")

        return H


# ---- page building -------------------------------------------------------------

def closed_page(state: str, title: str = "Pair with your Deck") -> str:
    text = {"done": "Your Deck is paired. You can close this page.",
            "expired": "This pairing link expired. Start pairing again on the Deck."}.get(
        state, "Pairing is closed. Start pairing again on the Deck.")
    return shell(title, f"<p>{html.escape(text)}</p>", form=False)


def sgdb_section(has_key: bool, optional: bool = True) -> str:
    """The SteamGridDB API key field (posted as ``sgdb_key``)."""
    hint = ("A key is already saved. Paste a new one to replace it, or leave this blank." if has_key
            else ("Optional. " if optional else "")
            + "Adds logos, wide capsules and better backgrounds to installed games. "
              "Sign in to SteamGridDB, then copy the key from its API page.")
    return f"""
<h2>SteamGridDB artwork</h2>
<p class="hint">{hint}</p>
<a class="btn" href="{SGDB_KEY_PAGE}" target="_blank" rel="noopener noreferrer">Open SteamGridDB API page</a>
<label for="sgdb_key">SteamGridDB API key</label>
<input id="sgdb_key" name="sgdb_key" autocomplete="off" autocapitalize="off" spellcheck="false"
  placeholder="32 characters">"""


def shell(title: str, body: str, form: bool = True) -> str:
    """A full page. With ``form``, a "Send to Deck" button posts every element with a
    ``name`` attribute as JSON and clears the fields on success."""
    send = """
<button id="send">Send to Deck</button>
<div id="msg"></div>
<script>
const msg = document.getElementById("msg"), send = document.getElementById("send");
// Form controls in the page body only (the <head> has <meta name=...>, which has no value).
const fields = () => Array.from(document.querySelectorAll("main input[name], main textarea[name], main select[name]"));
send.addEventListener("click", async () => {
  msg.className = ""; send.disabled = true;
  const body = Object.fromEntries(fields().map((f) => [f.name, (f.value || "").trim()]));
  try {
    const r = await fetch(location.pathname, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({ ok: false, message: "Pairing is closed. Start again on the Deck." }));
    msg.textContent = d.ok ? d.message + " You can close this page." : d.message;
    msg.className = d.ok ? "ok" : "err";
    if (d.ok) { fields().filter((f) => f.dataset.keep === undefined).forEach((f) => { f.value = ""; }); return; }
  } catch (e) {
    msg.textContent = "Couldn't reach the Deck. Is the pairing screen still open?"; msg.className = "err";
  }
  send.disabled = false;
});
</script>""" if form else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: dark; }}
body {{ margin: 0; font: 16px/1.45 system-ui, sans-serif; background: #0e141b; color: #dcdedf; }}
main {{ max-width: 520px; margin: 0 auto; padding: 24px 16px 48px; }}
h1 {{ font-size: 22px; margin: 0 0 6px; }}
p, li {{ color: #b8bcbf; }}
ol {{ padding-left: 20px; }}
label {{ display: block; font-size: 14px; margin: 18px 0 6px; color: #dcdedf; }}
h2 {{ font-size: 17px; margin: 28px 0 4px; }}
.hint {{ font-size: 14px; margin: 4px 0 0; }}
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
</style></head><body><main>{body}{send}</main></body></html>"""
