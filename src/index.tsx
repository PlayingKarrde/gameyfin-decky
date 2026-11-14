import {
  ButtonItem,
  DialogButton,
  Focusable,
  PanelSection,
  PanelSectionRow,
  SteamSpinner,
  showModal,
  staticClasses,
} from "@decky/ui";
import { definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaCog, FaServer, FaTimes } from "react-icons/fa";
import { PluginUpdate, PublicSettings, checkPluginUpdate, getSettings } from "./backend";
import { patchContextMenu } from "./contextMenu";
import { LIBRARY_ROUTE, LibraryPage, openLibrary } from "./components/LibraryPage";
import { DownloadsPanel } from "./components/DownloadsPanel";
import { InstallLocationPanel } from "./components/InstallLocationPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { ArtworkPanel } from "./common/ArtworkPanel";
import { PairingModal } from "./components/PairingModal";
import { healthOf, startPolling, stopPolling, useInstallState } from "./installs";
import { setPanelView, usePanelView } from "./view";

function LibraryButtons({ configured }: { configured: boolean }) {
  const { installed, status } = useInstallState();
  let updates = 0;
  let attention = 0;
  for (const inst of installed) {
    const st = status.find((s) => s.game_id === inst.game_id);
    if (healthOf(inst, st) !== "ok") attention++;
    else if (st?.update_available) updates++;
  }
  return (
    <PanelSection>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={!configured} onClick={() => openLibrary("all")}>
          Browse library
        </ButtonItem>
      </PanelSectionRow>
      {updates > 0 && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => openLibrary("updates")}>
            {updates === 1 ? "1 update available" : `${updates} updates available`}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {attention > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description="Missing files or a removed Steam shortcut"
            onClick={() => openLibrary("installed")}
          >
            {attention === 1 ? "1 install needs attention" : `${attention} installs need attention`}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

/** Decky's own "Install plugin from URL" flow: it asks for confirmation, then replaces this
 *  plugin with the release zip. The store isn't an option (it rejects LLM-written plugins). */
function installUpdate(u: PluginUpdate) {
  const backend = (window as any).DeckyBackend;
  if (!u.url || !backend?.call) {
    toaster.toast({ title: "Gameyfin", body: `Install ${u.latest} from ${u.page ?? "the GitHub releases page"}` });
    return;
  }
  // utilities/install_plugin(artifact, name, version, hash, install_type); 2 = InstallType.UPDATE.
  // hash false skips Decky's check when GitHub doesn't publish a digest.
  void backend.call("utilities/install_plugin", u.url, "Gameyfin", u.latest, u.sha256 ?? false, 2);
}

function PluginUpdateSection() {
  const [update, setUpdate] = useState<PluginUpdate | null>(null);
  useEffect(() => {
    checkPluginUpdate(false).then((r) => r.ok && setUpdate(r.data));
  }, []);
  if (!update?.newer) return null;
  return (
    <PanelSection title="Plugin update">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description={`Gameyfin for Decky ${update.latest} is available (you have ${update.current}).`}
          onClick={() => installUpdate(update)}
        >
          Update to {update.latest}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

/** Settings: ask GitHub now instead of waiting for the 6-hour cache. */
function UpdateCheckPanel() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ update?: PluginUpdate; error?: string } | null>(null);
  const update = result?.update;

  const onCheck = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await checkPluginUpdate(true);
      setResult(r.ok ? { update: r.data } : { error: r.error.message });
    } finally {
      setBusy(false);
    }
  };

  const description = busy
    ? "Checking…"
    : result?.error
      ? `Couldn't check: ${result.error}`
      : update
        ? update.newer
          ? `${update.latest} is available (you have ${update.current}).`
          : `You're on the latest version (${update.current}).`
        : undefined;

  return (
    <PanelSection title="Plugin">
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} description={description} onClick={onCheck}>
          Check for updates
        </ButtonItem>
      </PanelSectionRow>
      {update?.newer && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => installUpdate(update)}>
            Update to {update.latest}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

/** Mention a new release once per version, shortly after Steam starts. */
async function announceUpdate() {
  const r = await checkPluginUpdate(false);
  if (!r.ok || !r.data.newer) return;
  const KEY = "gameyfin-decky:announced-version";
  if (localStorage.getItem(KEY) === r.data.latest) return;
  localStorage.setItem(KEY, r.data.latest);
  toaster.toast({ title: "Gameyfin", body: `Version ${r.data.latest} is available. Update it from the Gameyfin panel.` });
}

function Content() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [pushed, setPushed] = useState<PublicSettings | null>(null);
  const view = usePanelView();
  const onSaved = (s: PublicSettings) => {
    setConfigured(!!s.server_url && s.has_token);
    setPushed(s);
  };

  // Leaving the plugin (B / Decky's back arrow) unmounts this; start on the main page next time.
  useEffect(() => () => setPanelView("main"), []);

  useEffect(() => {
    getSettings().then((r) => setConfigured(r.ok && !!r.data.server_url && r.data.has_token));
  }, []);

  if (configured === null) {
    return (
      <PanelSection>
        <SteamSpinner />
      </PanelSection>
    );
  }

  if (view === "settings") {
    return (
      <>
        <SettingsPanel onSaved={onSaved} />
        <InstallLocationPanel />
        <ArtworkPanel
          title="Gameyfin"
          settings={pushed}
          onSaved={onSaved}
          phone={(done) => showModal(<PairingModal onPaired={done} />)}
        />
        <UpdateCheckPanel />
      </>
    );
  }

  return (
    <>
      <PluginUpdateSection />
      <LibraryButtons configured={configured} />
      <DownloadsPanel />
      {!configured && <SettingsPanel onSaved={onSaved} />}
    </>
  );
}

const iconButton = { height: "28px", width: "40px", minWidth: 0, padding: "10px 12px" };

/** Title bar: "Gameyfin" plus a cog that opens settings; in settings it becomes a close button.
 *  (Decky draws its own back arrow on the left, which leaves the plugin.) */
function TitleView() {
  const view = usePanelView();
  const inSettings = view === "settings";
  return (
    <Focusable
      className={staticClasses.Title}
      style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%", padding: 0, boxShadow: "none" }}
    >
      <div style={{ marginRight: "auto" }}>{inSettings ? "Gameyfin settings" : "Gameyfin"}</div>
      <DialogButton style={iconButton} onClick={() => setPanelView(inSettings ? "main" : "settings")}>
        {inSettings ? (
          <FaTimes style={{ marginTop: "-4px", display: "block" }} />
        ) : (
          <FaCog style={{ marginTop: "-4px", display: "block" }} />
        )}
      </DialogButton>
    </Focusable>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(LIBRARY_ROUTE, LibraryPage, { exact: true });
  startPolling();
  const announce = setTimeout(() => void announceUpdate().catch(() => undefined), 30_000);
  let unpatchMenu = () => {};
  try {
    unpatchMenu = patchContextMenu();
  } catch (e) {
    console.warn("[gameyfin] context menu patch failed", e);
  }

  return {
    name: "Gameyfin",
    titleView: <TitleView />,
    content: <Content />,
    icon: <FaServer />,
    onDismount() {
      routerHook.removeRoute(LIBRARY_ROUTE);
      stopPolling();
      clearTimeout(announce);
      setPanelView("main");
      unpatchMenu();
    },
  };
});
