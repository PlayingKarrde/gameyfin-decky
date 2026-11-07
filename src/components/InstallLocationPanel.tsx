import { ButtonItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { openFilePicker, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { getInstallTargets, getSettings, setCustomInstallDir } from "../backend";

// FileSelectionType is a `const enum` in @decky/api's types and isn't exported at runtime.
const FOLDER = 1;

/** Optional extra install root shown in the install picker (internal + SD are automatic). */
export function InstallLocationPanel() {
  const [saved, setSaved] = useState("");
  const [home, setHome] = useState("/home/deck");

  useEffect(() => {
    getSettings().then((r) => r.ok && setSaved(r.data.custom_install_dir ?? ""));
    // The internal target is <home>/Games/Gameyfin; use its home as the picker's start.
    getInstallTargets().then((r) => {
      const internal = r.ok ? r.data.find((t) => t.id === "internal") : undefined;
      if (internal) setHome(internal.path.replace(/\/Games\/Gameyfin\/?$/, ""));
    });
  }, []);

  const save = async (path: string) => {
    const r = await setCustomInstallDir(path);
    if (r.ok) setSaved(r.data.custom_install_dir);
    toaster.toast({
      title: "Gameyfin",
      body: r.ok ? (path ? "Install folder saved" : "Custom install folder removed") : r.error.message,
    });
  };

  const browse = async () => {
    try {
      const res = await openFilePicker(FOLDER as any, saved || home, false, true);
      if (res?.path) await save(res.path);
    } catch {
      // picker closed without a choice
    }
  };

  return (
    <PanelSection title="Install location">
      <PanelSectionRow>
        <Field
          label="Custom folder"
          description={saved || "None. Internal storage and SD cards are offered automatically."}
          childrenLayout="below"
          focusable={false}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={browse}>
          {saved ? "Change folder…" : "Browse…"}
        </ButtonItem>
      </PanelSectionRow>
      {saved && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => save("")}>
            Clear custom folder
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
