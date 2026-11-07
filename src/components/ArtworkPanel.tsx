import { ButtonItem, Field, PanelSection, PanelSectionRow, TextField, ToggleField, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { PublicSettings, clearSgdbKey, getSettings, setSgdbKey, setSgdbSquareCovers } from "../backend";
import { PairingModal } from "./PairingModal";

type Props = {
  /** Latest settings pushed from elsewhere (e.g. a phone pairing in the Connection section). */
  settings?: PublicSettings | null;
  onSaved?: (s: PublicSettings) => void;
};

/** Optional SteamGridDB API key. The key is entered on the phone (SteamGridDB's Steam sign-in
 *  needs popups, which Decky's browser blocks) or typed here; it never comes back to the UI. */
export function ArtworkPanel({ settings, onSaved }: Props) {
  const [hasKey, setHasKey] = useState(false);
  const [square, setSquare] = useState(false);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings().then((r) => {
      if (!r.ok) return;
      setHasKey(r.data.has_sgdb_key);
      setSquare(r.data.sgdb_square_covers);
    });
  }, []);
  useEffect(() => {
    if (!settings) return;
    setHasKey(settings.has_sgdb_key);
    setSquare(settings.sgdb_square_covers);
  }, [settings]);

  const onSquare = async (on: boolean) => {
    setSquare(on);
    const r = await setSgdbSquareCovers(on);
    if (r.ok) onSaved?.(r.data);
    else setSquare(!on);
  };

  const saved = (s: PublicSettings, msg: string) => {
    setHasKey(s.has_sgdb_key);
    setKey("");
    setError(null);
    toaster.toast({ title: "Gameyfin", body: msg });
    onSaved?.(s);
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const onSave = () =>
    run(async () => {
      const r = await setSgdbKey(key.trim());
      if (r.ok) saved(r.data, "SteamGridDB key saved");
      else setError(r.error.message);
    });

  const onRemove = () =>
    run(async () => {
      const r = await clearSgdbKey();
      if (r.ok) saved(r.data, "SteamGridDB key removed");
    });

  return (
    <PanelSection title="SteamGridDB artwork">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description={
            hasKey
              ? "Key saved. New installs get a logo, hero and wide capsule from SteamGridDB."
              : "Optional. Adds logos and better backgrounds. Sign in to SteamGridDB on your phone and send its API key here."
          }
          onClick={() => showModal(<PairingModal onPaired={(s) => saved(s, "Paired from phone")} />)}
        >
          {hasKey ? "Replace key with phone" : "Add key with phone"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField
          label="API key"
          bIsPassword
          value={key}
          onChange={(e) => setKey(e.target.value)}
          description="Or type it: steamgriddb.com → Preferences → API"
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy || !key.trim()} onClick={onSave}>
          Save key
        </ButtonItem>
      </PanelSectionRow>
      {hasKey && (
        <PanelSectionRow>
          <ToggleField
            label="Square covers"
            description="Use SteamGridDB's square art for the library cover instead of the poster. Applies to new installs; use Refresh artwork for existing games."
            checked={square}
            onChange={onSquare}
          />
        </PanelSectionRow>
      )}
      {hasKey && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={onRemove}>
            Remove key
          </ButtonItem>
        </PanelSectionRow>
      )}
      {error && (
        <PanelSectionRow>
          <Field
            focusable={false}
            childrenLayout="below"
            description={<span style={{ color: "#ff6b6b", wordBreak: "break-word" }}>{error}</span>}
          />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
