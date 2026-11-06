import { DialogButton, Focusable, ModalRoot, Navigation, SteamSpinner, showModal } from "@decky/ui";
import { useEffect, useState } from "react";
import { ACTIVE_PHASES, GameDetail, GameSummary, formatBytes, getGame, platformLabel } from "../backend";
import { useInstallState } from "../installs";
import { shortcutExists } from "../steam";
import { InstallTargetModal, confirmUninstall } from "./InstallModals";
import { Cover } from "./Cover";

type Props = { game: GameSummary; closeModal?: () => void };

export function GameModal({ game, closeModal }: Props) {
  const [detail, setDetail] = useState<GameDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { jobs, installed } = useInstallState();
  // An old failed/cancelled job may still be listed; the in-progress one is what matters.
  const job = jobs.find(
    (j) => String(j.game_id) === String(game.id) && (ACTIVE_PHASES.includes(j.phase) || j.phase === "done"),
  );
  const inst = installed.find((g) => g.game_id === String(game.id));
  const busy = !!job;

  useEffect(() => {
    getGame(game.id).then((r) => (r.ok ? setDetail(r.data) : setError(r.error.message)));
  }, [game.id]);

  const meta = [
    detail?.release?.slice(0, 4) ?? game.release?.slice(0, 4),
    formatBytes(game.file_size),
    ...(game.platforms ?? []).map(platformLabel),
    ...(detail?.genres ?? []).slice(0, 3).map((g) => g.charAt(0) + g.slice(1).toLowerCase()),
  ].filter(Boolean);

  const canOpen = !!inst?.appid && !busy && shortcutExists(inst.appid);
  const GAP = "20px";
  const COVER_W = "180px";

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
          {busy ? (
            <DialogButton disabled style={{ flex: 1, minWidth: 0 }}>
              {job!.phase === "done"
                ? "Finishing…"
                : `Installing… ${job!.total ? Math.floor((100 * job!.done) / job!.total) + "%" : ""}`}
            </DialogButton>
          ) : inst ? (
            <DialogButton style={{ flex: 1, minWidth: 0 }} onClick={() => confirmUninstall(inst)}>
              Uninstall
            </DialogButton>
          ) : (
            <DialogButton
              style={{ flex: 1, minWidth: 0 }}
              onClick={() =>
                showModal(<InstallTargetModal gameId={game.id} title={game.title} size={game.file_size} />)
              }
            >
              Install
            </DialogButton>
          )}
          <DialogButton style={{ flex: 1, minWidth: 0 }} onClick={closeModal}>
            Close
          </DialogButton>
        </Focusable>
      </div>
    </ModalRoot>
  );
}
