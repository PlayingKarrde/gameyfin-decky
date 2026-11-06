# Gameyfin for Decky

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that connects Steam Gaming Mode to a self-hosted [Gameyfin](https://github.com/gameyfin/gameyfin) server. Browse your library, install games as non-Steam shortcuts that run under Proton, and uninstall them again, all from the controller.

## Features

- **Library browser** — full-screen grid with cover art, search and game details.
- **One-button installs** — pick internal storage, an SD card or a custom folder. Downloads run in a separate background process, so they keep going if Decky restarts. Progress and cancel live in the Quick Access panel.
- **Proper Steam shortcuts** — the game's executable is detected automatically (helpers like `UnityCrashHandler` or `vc_redist` are skipped; you're asked to pick when it's ambiguous). The shortcut gets Proton and Gameyfin's cover, hero and header artwork.
- **Clean uninstall** — removes the shortcut and the game folder, and asks separately before deleting the Proton prefix, since that's usually where saves live.
- **Phone pairing** — instead of typing an 87-character token on the Deck, scan a QR code, create a token in Gameyfin on your phone and paste it there.

## Requirements

- Steam Deck or another SteamOS device with [Decky Loader](https://decky.xyz).
- A Gameyfin server **v2.6.0 or newer** (the version that added the public `/v1` API), reachable from the Deck.
- A Gameyfin **personal access token** (Gameyfin → Settings → Personal access tokens).

> **Gameyfin 2.6.0 download bug:** in 2.6.0 the API's download endpoint fails with HTTP 500 for every game. The plugin works around this by falling back to the download endpoint the Gameyfin web UI uses, which only works when **public access** is enabled in Gameyfin. Without public access, installs fail with a message explaining this until Gameyfin ships a fix.

## Install

This plugin is not on the Decky plugin store. Install it manually:

1. In Decky's settings, open **General** and turn on **Developer mode**.
2. Open the new **Developer** tab and choose **Install Plugin from URL**.
3. Paste the URL of the latest release zip (`gameyfin-decky-<version>.zip`) from this repository's **Releases** page.

To update, repeat with the newer release's URL.

## Usage

1. Open the Quick Access menu (`…` button) → **Gameyfin**.
2. Under **Connection**, choose **Pair with phone** and follow the steps, or type the server URL and token yourself. **Test connection** checks them.
3. Choose **Browse library**, pick a game and press **Install**.
4. When the download finishes, the game appears in your Steam library, ready to play. If the plugin can't tell which `.exe` is the game, the **Downloads** section asks you to choose.

Games install to `~/Games/Gameyfin/<Title>` (or `<SD card>/Games/Gameyfin/<Title>`). An install needs about twice the game's size free while it runs, because the archive and the extracted copy exist at the same time.

## Limitations

- Aimed at **portable** Windows games (a folder you can run directly). Games that need an installer (GOG `setup.exe` and similar) aren't handled yet.
- Downloads can't resume: Gameyfin doesn't support HTTP range requests, so an interrupted download starts over.
- Save games aren't synced. They stay in the game's Proton prefix on the device.

## Privacy and security

- The token is stored only on the device, in Decky's settings folder (`settings.json`, mode `0600`), and is never sent to the Steam UI.
- Phone pairing runs a small web page on your local network only while the pairing screen is open, at most 10 minutes. Its address contains a random one-time code, it shuts down after one successful pairing or after repeated wrong guesses, and it uses plain HTTP like a typical LAN Gameyfin install.

## Development

Needs Node.js with pnpm, and Python 3.11+.

```sh
pnpm install
pnpm build                               # frontend -> dist/index.js
pnpm typecheck
python3 -m unittest discover -s tests    # backend tests
scripts/package.sh                       # out/gameyfin-decky-<version>.zip
DECK_HOST=deck scripts/deploy.sh         # build, copy to a Deck over ssh, restart Decky
```

`scripts/gf.py` exercises the Gameyfin client from a PC (reads `serverurl` and `api` from `.env`), `tests/fake_gameyfin.py` is a fake server for testing downloads, and `scripts/cdp.py` runs JavaScript in the Deck's Steam UI through the CEF debugger. `CLAUDE.md` has more detail on the layout and the Deck setup.

Development of this plugin was assisted by an AI coding assistant.

## License

BSD 3-Clause. See [LICENSE](LICENSE).
