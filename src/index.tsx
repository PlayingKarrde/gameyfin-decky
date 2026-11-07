import { ButtonItem, PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin, routerHook } from "@decky/api";
import { useEffect, useState } from "react";
import { FaServer } from "react-icons/fa";
import { getSettings } from "./backend";
import { patchContextMenu } from "./contextMenu";
import { LIBRARY_ROUTE, LibraryPage, openLibrary } from "./components/LibraryPage";
import { DownloadsPanel } from "./components/DownloadsPanel";
import { InstallLocationPanel } from "./components/InstallLocationPanel";
import { SettingsPanel } from "./components/SettingsPanel";
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

function Content() {
  const [configured, setConfigured] = useState(false);

  useEffect(() => {
    getSettings().then((r) => r.ok && setConfigured(!!r.data.server_url && r.data.has_token));
  }, []);

  return (
    <>
      <LibraryButtons configured={configured} />
      <DownloadsPanel />
      <SettingsPanel onSaved={(s) => setConfigured(!!s.server_url && s.has_token)} />
      <InstallLocationPanel />
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(LIBRARY_ROUTE, LibraryPage, { exact: true });
  startPolling();
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
      unpatchMenu();
    },
  };
});
