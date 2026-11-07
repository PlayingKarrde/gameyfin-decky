#!/usr/bin/env python3
"""Run JS in the Deck's SharedJSContext (Steam UI + Decky) via the CEF debugger. Stdlib only.

  ssh -fN -L 18080:localhost:8080 deck      # once: tunnel the Deck's CEF debugger
  echo 'return appStore.GetAppOverviewByAppID(123)' | scripts/cdp.py -
  scripts/cdp.py file.js
  scripts/cdp.py --shot out.png              # screenshot the Big Picture window

The JS is the body of an async function: use `return` / `await`. A `call(method, ...args)`
helper (also named `gf` and `rm`) calls the backend of the plugin this script sits in
(its name is read from ../plugin.json).

Synced from decky-common; edit it there.
"""
import base64, json, os, socket, struct, sys, urllib.parse, urllib.request

def ws_connect(url):
    u = urllib.parse.urlparse(url)
    s = socket.create_connection((u.hostname, u.port), timeout=180)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    assert b" 101 " in buf.split(b"\r\n")[0], buf[:200]
    return s, buf.split(b"\r\n\r\n", 1)[1]

def send(s, text):
    data = text.encode(); mask = os.urandom(4); n = len(data)
    hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                          else bytes([0x80 | 127]) + struct.pack(">Q", n))
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

class Reader:
    def __init__(self, s, buf): self.s, self.buf = s, buf
    def take(self, n):
        while len(self.buf) < n:
            c = self.s.recv(65536)
            if not c: raise EOFError
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]; return out
    def msg(self):
        payload = b""
        while True:
            b0, b1 = self.take(2); n = b1 & 0x7F
            if n == 126: n = struct.unpack(">H", self.take(2))[0]
            elif n == 127: n = struct.unpack(">Q", self.take(8))[0]
            payload += self.take(n)
            if b0 & 0x80: return payload.decode()

def rpc(target_title, method, params):
    tabs = json.load(urllib.request.urlopen("http://127.0.0.1:18080/json"))
    tab = next(t for t in tabs if t["title"] == target_title)
    s, rest = ws_connect(tab["webSocketDebuggerUrl"].replace("localhost:8080", "127.0.0.1:18080"))
    send(s, json.dumps({"id": 1, "method": method, "params": params}))
    r = Reader(s, rest)
    while True:
        m = json.loads(r.msg())
        if m.get("id") == 1:
            return m.get("result", m)


if len(sys.argv) == 3 and sys.argv[1] == "--shot":
    res = rpc("Steam Big Picture Mode", "Page.captureScreenshot", {"format": "png"})
    with open(sys.argv[2], "wb") as f:
        f.write(base64.b64decode(res["data"]))
    sys.exit(0)
if len(sys.argv) != 2:
    sys.exit(__doc__)
PLUGIN = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin.json")))["name"]
PRELUDE = (f"const call = (m, ...a) => DeckyBackend.call('loader/call_plugin_method', {json.dumps(PLUGIN)}, m, ...a);\n"
           "const gf = call, rm = call;\n")
js = PRELUDE + (sys.stdin.read() if sys.argv[1] == "-" else open(sys.argv[1]).read())
res = rpc("SharedJSContext", "Runtime.evaluate", {
    "expression": f"(async () => {{ {js} }})()", "awaitPromise": True, "returnByValue": True})
if "exceptionDetails" in res:
    print("EXC:", json.dumps(res["exceptionDetails"])[:2000]); sys.exit(1)
print(json.dumps(res["result"].get("value"), indent=1)[:8000])
