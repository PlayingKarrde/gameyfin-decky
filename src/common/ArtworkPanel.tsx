// QAM section for the optional SteamGridDB API key. Synced from decky-common; edit it there.
//
// Backend contract (the plugin's src/backend.ts must export these):
//   PublicSettings                 type with has_sgdb_key: boolean and sgdb_square_covers: boolean
//   getSettings()                  -> Result<PublicSettings>
//   setSgdbKey(key)                -> Result<PublicSettings>   validates against SGDB before saving
//   clearSgdbKey()                 -> Result<PublicSettings>
//   setSgdbSquareCovers(enabled)   -> Result<PublicSettings>
import { ButtonItem, Field, PanelSection, PanelSectionRow, TextField, ToggleField } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { PublicSettings, clearSgdbKey, getSettings, setSgdbKey, setSgdbSquareCovers } from "../backend";

type Props = {
  /** Toast title, usually the plugin's name. */
  title: string;
  /** Latest settings pushed from elsewhere (e.g. a phone pairing in another section). */
  settings?: PublicSettings | null;
  onSaved?: (s: PublicSettings) => void;
  /** Optional "send the key from your phone" flow. SteamGridDB's Steam sign-in needs popups,
   *  which Decky's browser blocks, so a phone is the easy way to copy the key. Call done()
   *  with the saved settings when the phone has delivered it. */
  phone?: (done: (s: PublicSettings) => void) => void;
};

/** The key never comes back to the UI: only whether one is saved. */
export function ArtworkPanel({ title, settings, onSaved, phone }: Props) {
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
    toaster.toast({ title, body: msg });
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

  const savedText = "Key saved. New installs get a logo, hero and wide capsule from SteamGridDB.";
  return (
    <PanelSection title="SteamGridDB artwork">
      {phone ? (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={
              hasKey
                ? savedText
                : "Optional. Adds logos and better backgrounds. Sign in to SteamGridDB on your phone and send its API key here."
            }
            onClick={() => phone((s) => saved(s, "Paired from phone"))}
          >
            {hasKey ? "Replace key with phone" : "Add key with phone"}
          </ButtonItem>
        </PanelSectionRow>
      ) : (
        <PanelSectionRow>
          <Field
            focusable={false}
            childrenLayout="below"
            description={
              hasKey
                ? savedText
                : "Optional. Adds logos, backgrounds and wide capsules. Get a free API key at steamgriddb.com → Preferences → API."
            }
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <TextField
          label="API key"
          bIsPassword
          value={key}
          onChange={(e) => setKey(e.target.value)}
          description={phone ? "Or type it: steamgriddb.com → Preferences → API" : "32 characters"}
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
