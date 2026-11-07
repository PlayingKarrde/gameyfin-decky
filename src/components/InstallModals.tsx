import { ConfirmModal, DialogButton, Focusable, ModalRoot, SteamSpinner, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import {
  ExeCandidate,
  InstallTarget,
  InstalledGame,
  InstallStatus,
  formatBytes,
  forgetInstalled,
  getInstallTargets,
  listExecutables,
  prefixExists,
  startInstall,
  uninstallGame,
} from "../backend";
import { kick, refresh, refreshStatus, startUpdate } from "../installs";
import { removeShortcut } from "../steam";

const muted = { color: "#8b929a", fontSize: "13px" };

// Mirrors installer.check_space: the archive and the extracted copy coexist briefly.
const SPACE_MARGIN = 512 * 1024 * 1024;
export const spaceNeeded = (size: number | null | undefined) => (size ? size * 2 + SPACE_MARGIN : null);

export function InstallTargetModal({
  gameId,
  title,
  size,
  closeModal,
}: {
  gameId: string;
  title: string;
  size: number | null;
  closeModal?: () => void;
}) {
  const [targets, setTargets] = useState<InstallTarget[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getInstallTargets().then((r) => (r.ok ? setTargets(r.data) : setError(r.error.message)));
  }, []);

  const need = spaceNeeded(size);
  const pick = async (t: InstallTarget) => {
    setBusy(true);
    const r = await startInstall(gameId, t.path);
    setBusy(false);
    if (!r.ok) return setError(r.error.message);
    toaster.toast({ title: "Gameyfin", body: `Downloading ${title}` });
    kick();
    closeModal?.();
  };

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "22px", fontWeight: "bold", marginBottom: "6px" }}>Install {title}</div>
      <div style={{ ...muted, marginBottom: "14px" }}>
        {size ? `Download ${formatBytes(size)}. Needs about ${formatBytes(need)} free while installing.` : null}
      </div>
      {error && <div style={{ color: "#ff6b6b", marginBottom: "10px" }}>{error}</div>}
      {!targets ? (
        !error && <SteamSpinner />
      ) : (
        <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {targets.map((t) => {
            const tooSmall = need != null && t.free != null && t.free < need;
            return (
              <DialogButton key={t.id} disabled={busy || tooSmall} onClick={() => pick(t)} style={{ textAlign: "left" }}>
                <div>{t.label}</div>
                <div style={muted}>
                  {t.path} · {t.free != null ? `${formatBytes(t.free)} free` : "unknown free space"}
                  {tooSmall ? " · not enough space" : ""}
                </div>
              </DialogButton>
            );
          })}
        </Focusable>
      )}
    </ModalRoot>
  );
}

type ExePickerProps = {
  installDir: string;
  title: string;
  initial?: ExeCandidate[];
  onPick: (rel: string) => void;
  closeModal?: () => void;
};

export function ExePickerModal({ installDir, title, initial, onPick, closeModal }: ExePickerProps) {
  const [cands, setCands] = useState<ExeCandidate[] | null>(initial ?? null);

  useEffect(() => {
    listExecutables(installDir, title).then((r) => r.ok && setCands(r.data));
  }, [installDir]);

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "22px", fontWeight: "bold", marginBottom: "6px" }}>Choose the game executable</div>
      <div style={{ ...muted, marginBottom: "14px" }}>
        {title} · {installDir}
      </div>
      {!cands ? (
        <SteamSpinner />
      ) : cands.length === 0 ? (
        <div>No .exe files found.</div>
      ) : (
        <Focusable style={{ display: "flex", flexDirection: "column", gap: "6px", maxHeight: "60vh", overflowY: "auto" }}>
          {cands.map((c) => (
            <DialogButton
              key={c.path}
              style={{ textAlign: "left" }}
              onClick={() => {
                closeModal?.();
                onPick(c.path);
              }}
            >
              <div>{c.path}</div>
              <div style={muted}>
                {c.kind === "linux" ? "Linux (native)" : "Windows (Proton)"} · {formatBytes(c.size)}
              </div>
            </DialogButton>
          ))}
        </Focusable>
      )}
    </ModalRoot>
  );
}

function confirm(props: { title: string; body: string; ok: string; cancel?: string }): Promise<boolean> {
  return new Promise<boolean>((resolve) =>
    showModal(
      <ConfirmModal
        strTitle={props.title}
        strDescription={props.body}
        strOKButtonText={props.ok}
        strCancelButtonText={props.cancel}
        onOK={() => resolve(true)}
        onCancel={() => resolve(false)}
      />,
    ),
  );
}

export async function confirmUpdate(game: InstalledGame, st?: InstallStatus): Promise<void> {
  const size = st?.server_size
    ? ` Downloads ${formatBytes(st.server_size)} and needs about ${formatBytes(spaceNeeded(st.server_size))} free.`
    : "";
  const ok = await confirm({
    title: `Update ${game.title}?`,
    body:
      `Replaces the game folder with the server's current version.${size} ` +
      "Anything the game stores inside its own folder (some games keep settings or saves there) is replaced. " +
      "The Steam shortcut and Proton prefix are kept.",
    ok: "Update",
  });
  if (ok) await startUpdate(game);
}

/** Drop the record but keep files: for missing, moved or unrecognised folders. */
export async function confirmForget(game: InstalledGame, reason: string): Promise<void> {
  const ok = await confirm({
    title: `Remove ${game.title} from Gameyfin?`,
    body: `${reason} This removes the Steam shortcut and the plugin's record. No files are deleted.`,
    ok: "Remove",
  });
  if (!ok) return;
  if (game.appid) await removeShortcut(game.appid);
  const r = await forgetInstalled(game.game_id);
  toaster.toast({ title: "Gameyfin", body: r.ok ? `${game.title} removed` : r.error.message });
  void refresh().then(() => refreshStatus());
}

export async function confirmUninstall(game: InstalledGame): Promise<void> {
  const ok = await confirm({
    title: `Uninstall ${game.title}?`,
    body: `Removes the Steam shortcut and deletes ${game.install_dir}.`,
    ok: "Uninstall",
  });
  if (!ok) return;

  let removePrefix = false;
  if (game.appid) {
    const has = await prefixExists(game.appid);
    if (has.ok && has.data) {
      removePrefix = await confirm({
        title: "Delete Proton prefix too?",
        body: "The prefix usually holds this game's saves and settings. Keep it if you might reinstall.",
        ok: "Delete prefix",
        cancel: "Keep prefix",
      });
    }
    await removeShortcut(game.appid);
  }
  const r = await uninstallGame(game.game_id, removePrefix);
  if (!r.ok && r.error.code === "unsafe_delete") {
    // The folder isn't recognisably ours (marker gone or replaced): never delete it, but
    // don't leave the user stuck with a record that can't be uninstalled either.
    await confirmForget(game, `${r.error.message}.`);
    return;
  }
  toaster.toast({
    title: "Gameyfin",
    body: r.ok ? `${game.title} uninstalled` : `Uninstall failed: ${r.error.message}`,
  });
  void refresh().then(() => refreshStatus());
}
