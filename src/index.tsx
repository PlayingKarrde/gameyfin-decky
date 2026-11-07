import { ButtonItem, PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaServer } from "react-icons/fa";
import { PluginUpdate, PublicSettings, checkPluginUpdate, getSettings } from "./backend";
import { patchContextMenu } from "./contextMenu";
import { LIBRARY_ROUTE, LibraryPage, openLibrary } from "./components/LibraryPage";
import { DownloadsPanel } from "./components/DownloadsPanel";
import { InstallLocationPanel } from "./components/InstallLocationPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { ArtworkPanel } from "./components/ArtworkPanel";
import { healthOf, startPolling, stopPolling, useInstallState } from "./installs";

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
  const [configured, setConfigured] = useState(false);
  const [pushed, setPushed] = useState<PublicSettings | null>(null);
  const onSaved = (s: PublicSettings) => {
    setConfigured(!!s.server_url && s.has_token);
    setPushed(s);
  };

  useEffect(() => {
    getSettings().then((r) => r.ok && setConfigured(!!r.data.server_url && r.data.has_token));
  }, []);

  return (
    <>
      <PluginUpdateSection />
      <LibraryButtons configured={configured} />
      <DownloadsPanel />
      <SettingsPanel onSaved={onSaved} />
      <ArtworkPanel settings={pushed} onSaved={onSaved} />
      <InstallLocationPanel />
    </>
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
    titleView: <div className={staticClasses.Title}>Gameyfin</div>,
    content: <Content />,
    icon: <FaServer />,
    onDismount() {
      routerHook.removeRoute(LIBRARY_ROUTE);
      stopPolling();
      clearTimeout(announce);
      unpatchMenu();
    },
  };
});
