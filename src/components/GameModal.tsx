import { DialogButton, Focusable, ModalRoot, Navigation, SteamSpinner, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { ReactElement, useEffect, useState } from "react";
import { GameDetail, GameSummary, formatBytes, getGame, platformLabel } from "../backend";
import { activeJobFor, healthOf, readdToSteam, refreshStatus, statusFor, useInstallState } from "../installs";
import { shortcutExists } from "../steam";
import { ExePickerModal, InstallTargetModal, confirmForget, confirmUninstall, confirmUpdate } from "./InstallModals";
import { Cover } from "../common/Cover";

type Props = { game: GameSummary; closeModal?: () => void };

const WARN = "#ffb84d";

export function GameModal({ game, closeModal }: Props) {
  const [detail, setDetail] = useState<GameDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const snap = useInstallState();
  const job = activeJobFor(snap, game.id);
  const inst = snap.installed.find((g) => g.game_id === String(game.id));
  const st = statusFor(snap, game.id);
  const health = inst ? healthOf(inst, st) : "ok";
  const busy = !!job;

  useEffect(() => {
    getGame(game.id).then((r) => (r.ok ? setDetail(r.data) : setError(r.error.message)));
    if (inst) void refreshStatus(); // fresh update/health info for the game being looked at
  }, [game.id]);

  const meta = [
    detail?.release?.slice(0, 4) ?? game.release?.slice(0, 4),
    formatBytes(game.file_size),
    ...(game.platforms ?? []).map(platformLabel),
    ...(detail?.genres ?? []).slice(0, 3).map((g) => g.charAt(0) + g.slice(1).toLowerCase()),
  ].filter(Boolean);

  const canOpen = !!inst?.appid && !busy && health === "ok" && shortcutExists(inst.appid);
  const GAP = "20px";
  const COVER_W = "180px";

  const readd = async () => {
    if (!inst) return;
    const go = async (rel?: string) => {
      setWorking(true);
      try {
        await readdToSteam(inst, rel);
      } catch (e) {
        toaster.toast({ title: "Gameyfin", body: `Couldn't add ${inst.title} to Steam: ${(e as Error).message}` });
      } finally {
        setWorking(false);
      }
    };
    if (inst.exe) return go();
    showModal(<ExePickerModal installDir={inst.install_dir} title={inst.title} onPick={(rel) => void go(rel)} />);
  };

  const notice = !inst
    ? null
    : health === "files_missing"
      ? `The game files are missing from ${inst.install_dir}. Reinstall, or remove it from the list.`
      : health === "unmarked"
        ? `${inst.install_dir} no longer looks like this game's install, so it won't be deleted or updated.`
        : health === "shortcut_missing"
          ? "The Steam shortcut was removed. The game files are still installed."
          : st?.update_available
            ? `Update available: ${formatBytes(st.server_size)} on the server (installed ${formatBytes(inst.server_file_size ?? inst.size)}).`
            : st?.server_missing
              ? "This game is no longer on the Gameyfin server. The installed copy still works."
              : null;

  const wide = { flex: 1, minWidth: 0 };
  const install = () =>
    showModal(<InstallTargetModal gameId={game.id} title={game.title} size={game.file_size} />);

  let actions: ReactElement[];
  if (busy) {
    actions = [
      <DialogButton key="busy" disabled style={wide}>
        {job!.phase === "done"
          ? "Finishing…"
          : `${job!.kind === "update" ? "Updating" : "Installing"}… ${
              job!.total ? Math.floor((100 * job!.done) / job!.total) + "%" : ""
            }`}
      </DialogButton>,
    ];
  } else if (!inst) {
    actions = [
      <DialogButton key="install" style={wide} onClick={install}>
        Install
      </DialogButton>,
    ];
  } else if (health === "files_missing") {
    actions = [
      <DialogButton key="reinstall" style={wide} disabled={st?.server_missing} onClick={install}>
        Reinstall
      </DialogButton>,
      <DialogButton key="forget" style={wide} onClick={() => confirmForget(inst, "Its files are missing.")}>
        Remove
      </DialogButton>,
    ];
  } else if (health === "unmarked") {
    actions = [
      <DialogButton
        key="forget"
        style={wide}
        onClick={() => confirmForget(inst, "Its folder is no longer recognised as this game.")}
      >
        Remove
      </DialogButton>,
    ];
  } else {
    actions = [];
    if (health === "shortcut_missing")
      actions.push(
        <DialogButton key="readd" style={wide} disabled={working} onClick={readd}>
          Re-add to Steam
        </DialogButton>,
      );
    if (st?.update_available)
      actions.push(
        <DialogButton key="update" style={wide} onClick={() => confirmUpdate(inst, st)}>
          Update
        </DialogButton>,
      );
    actions.push(
      <DialogButton key="uninstall" style={wide} onClick={() => confirmUninstall(inst)}>
        Uninstall
      </DialogButton>,
    );
  }

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ display: "flex", flexDirection: "column", gap: GAP }}>
        <div style={{ display: "flex", gap: GAP, minHeight: "270px" }}>
          <div style={{ width: COVER_W, flexShrink: 0 }}>
            <Cover url={game.cover} title={game.title} />
          </div>
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: "10px" }}>
            <div style={{ fontSize: "24px", fontWeight: "bold" }}>{game.title}</div>
            <div style={{ color: "#8b929a", fontSize: "14px" }}>{meta.join(" · ")}</div>
            {detail?.developers.length ? (
              <div style={{ fontSize: "13px", color: "#b8bcbf" }}>{detail.developers.join(", ")}</div>
            ) : null}
            {inst?.deps?.length ? (
              <div style={{ fontSize: "13px", color: "#8b929a" }}>
                Dependencies, installed on first launch: {inst.deps.join(", ")}
              </div>
            ) : null}
            {notice && (
              <div
                style={{
                  fontSize: "13px",
                  color: st?.update_available && health === "ok" ? "#1a9fff" : WARN,
                  wordBreak: "break-word",
                }}
              >
                {notice}
              </div>
            )}
            <div style={{ fontSize: "13px", lineHeight: 1.4, maxHeight: "180px", overflowY: "auto", color: "#dcdedf" }}>
              {error ? (
                <span style={{ color: "#ff6b6b" }}>{error}</span>
              ) : detail ? (
                detail.summary ?? "No description."
              ) : (
                <SteamSpinner />
              )}
            </div>
          </div>
        </div>

        {/* One button group: the first slot sits under the poster, the rest under the text,
            all with the same gap, so left/right moves through every button. */}
        <Focusable style={{ display: "flex", gap: GAP }} flow-children="horizontal">
          {canOpen ? (
            <DialogButton
              style={{ width: COVER_W, minWidth: 0, flexShrink: 0 }}
              onClick={() => {
                closeModal?.();
                Navigation.Navigate(`/library/app/${inst!.appid}`);
              }}
            >
              Open in library
            </DialogButton>
          ) : (
            <div style={{ width: COVER_W, flexShrink: 0 }} />
          )}
          {actions}
          <DialogButton style={wide} onClick={closeModal}>
            Close
          </DialogButton>
        </Focusable>
      </div>
    </ModalRoot>
  );
}
