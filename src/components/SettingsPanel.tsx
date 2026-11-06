import { ButtonItem, Field, PanelSection, PanelSectionRow, TextField, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { ConnectionInfo, PublicSettings, getSettings, saveSettings, testConnection } from "../backend";
import { PairingModal } from "./PairingModal";

type Props = { onSaved?: (s: PublicSettings) => void };

/** Server URL + API token form with test/save. The saved token is never sent to the UI. */
export function SettingsPanel({ onSaved }: Props) {
  const [loaded, setLoaded] = useState<PublicSettings | null>(null);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    getSettings().then((r) => {
      if (r.ok) {
        setLoaded(r.data);
        setUrl(r.data.server_url);
      }
    });
  }, []);

  const describe = (c: ConnectionInfo) =>
    [
      `Connected${c.server_version ? ` to Gameyfin ${c.server_version}` : ""}`,
      c.username ? `as ${c.username}` : "(service key)",
      `· ${c.game_count ?? "?"} games`,
      c.download_providers.length ? "" : "· ⚠ no download providers",
    ]
      .filter(Boolean)
      .join(" ");

  const onTest = async () => {
    setBusy(true);
    setStatus(null);
    try {
      const r = await testConnection(url || null, token || null);
      setStatus(r.ok ? { ok: true, text: describe(r.data) } : { ok: false, text: r.error.message });
    } finally {
      setBusy(false);
    }
  };

  const onSave = async () => {
    setBusy(true);
    try {
      const r = await saveSettings(url, token || null);
      if (r.ok) {
        setLoaded(r.data);
        setUrl(r.data.server_url);
        setToken("");
        toaster.toast({ title: "Gameyfin", body: "Settings saved" });
        onSaved?.(r.data);
      } else {
        setStatus({ ok: false, text: r.error.message });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Connection">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description="Easiest: paste the token from your phone instead of typing it here."
          onClick={() =>
            showModal(
              <PairingModal
                onPaired={(s) => {
                  setLoaded(s);
                  setUrl(s.server_url);
                  setToken("");
                  setStatus({ ok: true, text: "Paired from phone" });
                  onSaved?.(s);
                }}
              />,
            )
          }
        >
          Pair with phone
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField
          label="Server URL"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          description="e.g. http://192.168.1.10:8080"
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField
          label="API token"
          bIsPassword
          value={token}
          onChange={(e) => setToken(e.target.value)}
          description={
            loaded?.has_token ? "A token is saved. Leave blank to keep it." : "Gameyfin → Settings → Personal access tokens"
          }
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy || !url} onClick={onTest}>
          Test connection
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy || !url || (!token && !loaded?.has_token)} onClick={onSave}>
          Save
        </ButtonItem>
      </PanelSectionRow>
      {status && (
        <PanelSectionRow>
          <Field
            focusable={false}
            childrenLayout="below"
            description={
              <span style={{ color: status.ok ? "#59bf40" : "#ff6b6b", wordBreak: "break-word" }}>{status.text}</span>
            }
          />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
