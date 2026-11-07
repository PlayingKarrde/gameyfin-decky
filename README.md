# Gameyfin for Decky

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that connects Steam Gaming Mode to a self-hosted [Gameyfin](https://github.com/gameyfin/gameyfin) server. Browse your library, install games as non-Steam shortcuts that run under Proton, and uninstall them again, all from the controller.

## Features

- **Library browser**: a full-screen grid with cover art, search, a library filter and game details. The **Installed** and **Updates** tabs show what's on the device.
- **One-button installs**: pick internal storage, an SD card or a custom folder (chosen with a folder browser). Downloads run in a separate background process, so they keep going if Decky restarts. Progress and cancel are in the Quick Access panel. Before downloading, the plugin checks there's enough free space.
- **Proper Steam shortcuts**:
  - The game's executable is detected automatically. Helpers like `UnityCrashHandler` or `vc_redist` are skipped, and you're asked to pick when it's ambiguous.
  - Windows games run under Proton. Native Linux builds (`start.sh`, `.x86_64` and similar) run directly.
  - The shortcut gets Gameyfin's cover, hero and header artwork.
- **GOG offline installers**: a folder holding `setup_*.exe` and its `.bin` parts is unpacked with a bundled [innoextract](https://constexpr.org/innoextract/), no Wine needed. DLC installers in the same folder are layered on top of the base game, and GOG's launch settings (arguments, working folder) are applied to the shortcut.
- **Bundled dependencies**: if a Windows game ships Visual C++, DirectX, XNA or OpenAL installers (GOG's `__redist`, `_CommonRedist` and similar), they run silently in the game's Proton prefix on its first launch. You can turn this off in the plugin's **Installs** section.
- **Updates**: the plugin notices when the server has a different build of an installed game, and updates it in place. The shortcut, Proton prefix, artwork and launch options are kept.
- **Repair**: installs with missing files or a deleted Steam shortcut are flagged and can be re-added or reinstalled.
- **Steam context menu**: Gameyfin games get a **Gameyfin** submenu in the library's context menu, with **Update…** and **Uninstall…**. Steam's own "Remove non-Steam game" only deletes the shortcut.
- **Clean uninstall**: removes the shortcut and the game folder, and asks separately before deleting the Proton prefix, since that's usually where saves live.
- **Phone pairing**: instead of typing an 87-character token on the Deck, scan a QR code, create a token in Gameyfin on your phone and paste it there.
- **Plugin updates**: the Quick Access panel tells you when a new release is out and installs it through Decky's own confirmation dialog.

## Requirements

- Steam Deck or another SteamOS device with [Decky Loader](https://decky.xyz).
- A Gameyfin server **v2.6.0 or newer** (the version that added the public `/v1` API), reachable from the Deck.
- A Gameyfin **personal access token** (Gameyfin → Settings → Personal access tokens).

> **Gameyfin 2.6.0 download bug:** in 2.6.0 the API's download endpoint fails with HTTP 500 for every game. The plugin works around this by falling back to the download endpoint the Gameyfin web UI uses, which only works when **public access** is enabled in Gameyfin. Without public access, installs fail with a message explaining this until Gameyfin ships a fix.

## Install

This plugin is not on the Decky plugin store. Install it manually:

1. In Decky's settings, open **General** and turn on **Developer mode**.
2. Open the new **Developer** tab and choose **Install Plugin from URL**.
3. Paste the URL of the latest release zip from this repository's **Releases** page, for example:
   `https://github.com/PlayingKarrde/gameyfin-decky/releases/download/v0.5.0/gameyfin-decky-0.5.0.zip`

After that, the plugin offers new versions itself (**Update to …** at the top of its Quick Access panel). You can also repeat the steps above with a newer release's URL.

## Usage

1. Open the Quick Access menu (`…` button) → **Gameyfin**.
2. Under **Connection**, choose **Pair with phone** and follow the steps, or type the server URL and token yourself. **Test connection** checks them.
3. Choose **Browse library**, pick a game and press **Install**.
4. When the download finishes, the game appears in your Steam library, ready to play. If the plugin can't tell which executable is the game, the **Downloads** section asks you to choose.

Games install to `~/Games/Gameyfin/<Title>` (or `<SD card>/Games/Gameyfin/<Title>`, or your custom folder). An install needs about twice the game's size free while it runs, because the archive and the extracted copy exist at the same time.

### How to lay out games in Gameyfin

- **Portable games**: the game's folder as you'd run it, with the `.exe` (or Linux launcher) inside.
- **GOG offline installers**: the installer files on their own in the game's folder: `setup_<game>_<version>.exe` plus its `-1.bin`, `-2.bin`… parts. Put DLC installers (`setup_<game>_<dlc>_….exe`) in the same folder. Don't mix installers with an already-installed copy of the game, or the plugin treats the folder as a portable game.

## Limitations

- **Installers**: only Inno Setup installers (what GOG uses) are unpacked. Other installers (NSIS, MSI, InstallShield) aren't run. GOG **patch** installers (`patch_*.exe`) can't be applied; use the latest full installer instead. If a DLC installer can't be unpacked, the base game is still installed, the DLC installer is left in the folder, and you get a notification.
- **Dependencies**: only Visual C++, DirectX, XNA and OpenAL installers are recognised, and only ones shipped inside the game's folder. .NET installers are skipped, since Proton has its own .NET support (wine-mono). The first launch takes longer while they install, and a log is kept in the prefix (`compatdata/<appid>/gameyfin-deps.log`). If you delete the prefix, they run again on the next launch. The shortcut's launch options start with `/bin/bash ".../.gameyfin-deps/run.sh" %command%`: keep that part if you edit them.
- **Downloads can't resume**: Gameyfin doesn't support HTTP range requests, so an interrupted download starts over.
- **Save games aren't synced.** They stay in the game's Proton prefix on the device.

## Privacy and security

- Apart from your Gameyfin server, the only other connection is a check of this repository's latest GitHub release, at most every few hours while Decky is running.

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
