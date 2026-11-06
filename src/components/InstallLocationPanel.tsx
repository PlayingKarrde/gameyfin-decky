import { ButtonItem, PanelSection, PanelSectionRow, TextField } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { getSettings, setCustomInstallDir } from "../backend";

/** Optional extra install root shown in the install picker (internal + SD are automatic). */
export function InstallLocationPanel() {
  const [path, setPath] = useState("");
  const [saved, setSaved] = useState("");

  useEffect(() => {
    getSettings().then((r) => {
      if (r.ok) {
        setPath(r.data.custom_install_dir ?? "");
        setSaved(r.data.custom_install_dir ?? "");
      }
    });
  }, []);

  const save = async () => {
    const r = await setCustomInstallDir(path);
    if (r.ok) setSaved(r.data.custom_install_dir);
    toaster.toast({ title: "Gameyfin", body: r.ok ? "Install folder saved" : r.error.message });
  };

  return (
    <PanelSection title="Install location">
      <PanelSectionRow>
        <TextField
          label="Custom folder (optional)"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          description="Internal storage and SD cards are offered automatically."
        />
      </PanelSectionRow>
      {path !== saved && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={save}>
            Save folder
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
