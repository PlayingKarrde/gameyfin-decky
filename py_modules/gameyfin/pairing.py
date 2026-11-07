"""Phone pairing page for Gameyfin: the API token and an optional SteamGridDB API key.

Typing an ~87-character token with the Deck's on-screen keyboard is painful, so the
phone opens a short-lived LAN page (common/phoneform.py), follows a link to Gameyfin's
/settings/tokens, creates a token and pastes it back. We validate it before saving.
The same page takes the SteamGridDB key (SGDB's Steam sign-in needs popups, which
Decky's browser blocks; the phone's browser handles that fine).
"""

from __future__ import annotations

import html
import urllib.parse
from typing import Callable

from .common.phoneform import PhoneForm, sgdb_section, shell

TITLE = "Pair Gameyfin with your Deck"

# (server_url, token, sgdb_key) -> message on success; raise to reject (shown on the phone).
# token or sgdb_key may be "" when the user only sends the other one.
Submit = Callable[[str, str, str], str]


def session(server_url: str, submit: Submit, has_token: bool = False, has_sgdb_key: bool = False) -> PhoneForm:
    def on_post(fields: dict) -> str:
        url, token, key = fields.get("server_url", ""), fields.get("token", ""), fields.get("sgdb_key", "")
        if not token and not key:
            raise ValueError("Paste a Gameyfin token or a SteamGridDB key")
        if token and not url:
            raise ValueError("Server URL is required")
        return submit(url, token, key)

    hint = urllib.parse.urlparse(server_url).hostname if server_url else None
    return PhoneForm(lambda: page(server_url, has_token, has_sgdb_key), on_post, hint_host=hint, closed_title=TITLE)


def page(server_url: str, has_token: bool = False, has_sgdb_key: bool = False) -> str:
    token_hint = ("Your Deck already has a token. Leave this blank to keep it." if has_token
                  else "In Gameyfin, create a <b>personal access token</b> and paste it here.")
    body = f"""
<h1>{TITLE}</h1>
<h2>Gameyfin</h2>
<p class="hint">{token_hint}</p>
<label for="url">Gameyfin server</label>
<input id="url" name="server_url" data-keep type="url" inputmode="url" autocomplete="off"
  placeholder="http://192.168.1.10:8080" value="{html.escape(server_url)}">
<a class="btn" id="open" target="_blank" rel="noopener noreferrer">Open Gameyfin token page</a>
<label for="token">Personal access token</label>
<textarea id="token" name="token" autocomplete="off" autocapitalize="off" spellcheck="false"
  placeholder="gf_pat_…"></textarea>
{sgdb_section(has_sgdb_key)}
<script>
const url = document.getElementById("url"), open = document.getElementById("open");
const syncLink = () => {{ open.href = url.value.trim().replace(/\\/+$/, "") + "/settings/tokens"; }};
url.addEventListener("input", syncLink); syncLink();
</script>"""
    return shell(TITLE, body)
