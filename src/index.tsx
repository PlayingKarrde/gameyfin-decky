import { ButtonItem, Navigation, PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin, routerHook } from "@decky/api";
import { useEffect, useState } from "react";
import { FaServer } from "react-icons/fa";
import { getSettings } from "./backend";
import { LIBRARY_ROUTE, LibraryPage } from "./components/LibraryPage";
import { DownloadsPanel } from "./components/DownloadsPanel";
import { InstallLocationPanel } from "./components/InstallLocationPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { startPolling, stopPolling } from "./installs";

function Content() {
  const [configured, setConfigured] = useState(false);

  useEffect(() => {
    getSettings().then((r) => r.ok && setConfigured(!!r.data.server_url && r.data.has_token));
  }, []);

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!configured}
            onClick={() => {
              Navigation.Navigate(LIBRARY_ROUTE);
              Navigation.CloseSideMenus();
            }}
          >
            Browse library
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <DownloadsPanel />
      <SettingsPanel onSaved={(s) => setConfigured(!!s.server_url && s.has_token)} />
      <InstallLocationPanel />
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(LIBRARY_ROUTE, LibraryPage, { exact: true });
  startPolling();

  return {
    name: "Gameyfin",
    titleView: <div className={staticClasses.Title}>Gameyfin</div>,
    content: <Content />,
    icon: <FaServer />,
    onDismount() {
      routerHook.removeRoute(LIBRARY_ROUTE);
      stopPolling();
    },
  };
});
