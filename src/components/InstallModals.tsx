import { ConfirmModal, DialogButton, Focusable, ModalRoot, SteamSpinner, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import {
  ExeCandidate,
  InstallTarget,
  InstalledGame,
  JobState,
  formatBytes,
  getInstallTargets,
  listExecutables,
  prefixExists,
  startInstall,
  uninstallGame,
} from "../backend";
import { finishInstall, kick, refresh } from "../installs";
import { removeShortcut } from "../steam";

const muted = { color: "#8b929a", fontSize: "13px" };

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

  const need = size ? size * 2 : null;
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

export function ExePickerModal({ job, closeModal }: { job: JobState; closeModal?: () => void }) {
  const [cands, setCands] = useState<ExeCandidate[] | null>(job.exe_candidates ?? null);

  useEffect(() => {
    if (job.install_dir)
      listExecutables(job.install_dir, job.title ?? "").then((r) => r.ok && setCands(r.data));
  }, [job.install_dir]);

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "22px", fontWeight: "bold", marginBottom: "6px" }}>Choose the game executable</div>
      <div style={{ ...muted, marginBottom: "14px" }}>{job.title} · {job.install_dir}</div>
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
                void finishInstall(job, c.path, true);
              }}
            >
              <div>{c.path}</div>
              <div style={muted}>{formatBytes(c.size)}</div>
            </DialogButton>
          ))}
        </Focusable>
      )}
    </ModalRoot>
  );
}

export async function confirmUninstall(game: InstalledGame): Promise<void> {
  const ok = await new Promise<boolean>((resolve) =>
    showModal(
      <ConfirmModal
        strTitle={`Uninstall ${game.title}?`}
        strDescription={`Removes the Steam shortcut and deletes ${game.install_dir}.`}
        strOKButtonText="Uninstall"
        onOK={() => resolve(true)}
        onCancel={() => resolve(false)}
      />,
    ),
  );
  if (!ok) return;

  let removePrefix = false;
  if (game.appid) {
    const has = await prefixExists(game.appid);
    if (has.ok && has.data) {
      removePrefix = await new Promise<boolean>((resolve) =>
        showModal(
          <ConfirmModal
            strTitle="Delete Proton prefix too?"
            strDescription="The prefix usually holds this game's saves and settings. Keep it if you might reinstall."
            strOKButtonText="Delete prefix"
            strCancelButtonText="Keep prefix"
            onOK={() => resolve(true)}
            onCancel={() => resolve(false)}
          />,
        ),
      );
    }
    await removeShortcut(game.appid);
  }
  const r = await uninstallGame(game.game_id, removePrefix);
  toaster.toast({
    title: "Gameyfin",
    body: r.ok ? `${game.title} uninstalled` : `Uninstall failed: ${r.error.message}`,
  });
  void refresh();
}
