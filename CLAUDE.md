# gameyfin-decky

Decky Loader plugin: browse a self-hosted Gameyfin server from Steam Gaming Mode, install games (mostly portable folders) as non-Steam shortcuts running under Proton, and uninstall them. Full background and roadmap: `HANDOFF.md` (local only, git-ignored).

## Hard constraints
- **Gameyfin only.** No RomM code (Tender covers that).
- **Stay a Decky plugin**, not a standalone service. Downloads and extraction run in a **separate worker process** that survives Decky restarts. The UI reads progress from a state file or socket.
- Decky's bridge payload cap is about 1 MiB: send small JSON and progress events only, never bulk data.
- Runtime tools must ship with the plugin (`py_modules/`, bundled bins) or come with SteamOS. The root filesystem is read-only.
- The plugin runs as the `deck` user (no `_root` flag) so game files and prefixes aren't root-owned.
- Save handling is out of scope for v1 and v2.

## Layout
- `main.py`: Python backend (`class Plugin`; public async methods are callable from TS via `callable()`).
- `src/index.tsx`: React frontend (`@decky/ui`, `@decky/api`).
- `py_modules/`: on `sys.path` at runtime. `py_modules/gameyfin/` is our backend package: `client.py` (stdlib-only API client, shared with the future worker), `settings.py`, `images.py` (auth-required images are cached on disk and sent to the UI as data URLs), `library.py` (slim payloads), `installer.py` (download + extract), `jobs.py` (job dirs + launching the worker), `worker.py` (`python3 -m gameyfin.worker <job_dir>`), `exes.py` (exe ranking, native Linux launchers, GOG `goggame-*.info` play tasks), `installers.py` (GOG/Inno installers via the bundled `bin/innoextract`: base game + DLC layered in, patches left alone), `deps.py` (bundled VC++/DirectX/XNA/OpenAL installers: writes `<game>/.gameyfin-deps/run.sh`, which the shortcut runs as `/bin/bash run.sh %command%` to install them once per prefix through Steam's own Proton command), `selfupdate.py` (GitHub latest-release check; the frontend installs updates through Decky's `utilities/install_plugin`), `status.py` (drift and update checks), `installed.py` (installed.json record, install targets, safe delete).
- Install flow: `start_install` creates `<runtime>/jobs/<id>/` and launches the worker with system `/usr/bin/python3` as a transient `systemd-run --user` unit, so it survives Decky restarts (verified on the Deck). The worker reads the token from settings.json and writes `state.json`. The frontend poller (`src/installs.ts`, started in `definePlugin`) turns `done` jobs into shortcuts: `register_installed`, then `dismiss_job`. Jobs whose exe is ambiguous wait in the QAM "Downloads" section for a pick.
- `src/steam.ts` holds every `SteamClient.Apps.*` call. Verified on the Deck: AddShortcut, then SetShortcutExe/StartDir with **quoted** paths, then SpecifyCompatTool(`proton_experimental`). A reinstall reuses the recorded appid.
- Backend callables return `{ok, data}` or `{ok: false, error: {message, status, code}}`. The token is never sent to the frontend.
- Gameyfin accepts personal tokens (`gf_pat_`) or service keys (`gf_key_`). `/v1/me` only works with personal tokens, so don't depend on it.
- `decky.pyi`: type stubs for the injected `decky` module.
- `scripts/deploy.sh`: build, rsync to the Deck, restart Decky. `scripts/logs.sh`: tail logs.

## Commands
- `pnpm build` / `pnpm watch` / `pnpm typecheck`
- `scripts/package.sh`: builds `out/gameyfin-decky-<version>.zip` (the release artifact; deploy.sh uses the same staging). Releases: bump `package.json` version, then push tag `v<version>`; `.github/workflows/release.yml` attaches the zip. Not on the Decky store, which rejects LLM-written plugins; users install it manually from the release URL.
- `scripts/deploy.sh` (env: `DECK_HOST`, default `deck`; `NO_BUILD=1`, `NO_RESTART=1`)
- `scripts/logs.sh [lines] [-f|--loader]`
- `scripts/cdp.py -|file.js`: run JS in the Deck's SharedJSContext. First run `ssh -fN -L 18080:localhost:8080 deck`. `gf(method, ...args)` calls our backend. Use it to test SteamClient calls and drive installs without touching the UI.
- `tests/fake_gameyfin.py`: a fake server that streams a STORED zip. On the Deck, run it with `systemd-run --user` (a plain nohup dies with the ssh session).
- `python3 -m unittest discover -s tests`
- `scripts/gf.py test|list [q]|game <id>|providers|install <id> --dest DIR`: exercise the Gameyfin client from the PC using `.env` (`serverurl`, `api`). `.env` is git-ignored and must never be printed.
- Deploy mechanics: Decky re-chowns `~/homebrew/plugins/<name>` to root on every start. `deploy.sh` therefore rsyncs to `~/.cache/gameyfin-decky-stage/`, then runs one exact-args `sudo rsync` into the plugin dir. Both that rsync and `systemctl restart plugin_loader` are NOPASSWD in `/etc/sudoers.d/zz-decky-dev` on the Deck. The file name must sort after `wheel`, because the last matching sudoers rule wins.
- Node and pnpm are installed in `~/.local/bin` on the dev PC (WSL). The Windows npm on PATH must not be used.

## Gameyfin API notes (v2.6.0)
- Auth header `X-API-Key`. Base `/v1`. OpenAPI at `/v3/api-docs`.
- Downloads are on-the-fly **STORED zips with data descriptors and no Range support**. Write the whole file to disk (same filesystem as the target), then extract with `zipfile`. Need about 2× `fileSize` free. Downloads may also be a raw single file, or JSON `{kind:"link",url}` (fetch without `X-API-Key`).
- Download provider keys are opaque: discover them via `/v1/download-providers`.

## Steam integration
`SteamClient.Apps.*` is undocumented and changes often. Copy patterns from working plugins (Unifideck, Junk Store, decky-steamgriddb, Tender) and try calls in the CEF debugger before writing code.
