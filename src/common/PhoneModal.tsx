// QR code + short URL for a phone form (deckycommon/phoneform.py). Synced from decky-common;
// edit it there. The backend calls come in as props (not from ../backend), since plugins
// name them differently (romm-decky's start_pairing is RomM's own device sign-in).
import { DialogButton, Focusable, ModalRoot, SteamSpinner } from "@decky/ui";
import { toaster } from "@decky/api";
import qrcode from "qrcode-generator";
import { ReactNode, useEffect, useMemo, useState } from "react";

type R<T> = { ok: true; data: T } | { ok: false; error: { message: string } };

export type PhoneFormStatus<S> = {
  state: "waiting" | "done" | "expired" | "stopped" | "locked";
  url?: string;
  code?: string;
  message?: string;
  expires_in?: number;
  /** The plugin's public settings after a successful post. */
  settings?: S;
};

export type PhoneFormApi<S> = {
  start: () => Promise<R<PhoneFormStatus<S>>>;
  status: () => Promise<R<PhoneFormStatus<S>>>;
  stop: () => Promise<unknown>;
};

type Props<S> = {
  api: PhoneFormApi<S>;
  /** Toast title, usually the plugin's name. */
  title: string;
  /** What the phone page asks for. */
  description: ReactNode;
  onDone?: (s: S) => void;
  closeModal?: () => void;
};

function qrSvg(text: string): string {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
}

export function PhoneModal<S>({ api, title, description, onDone, closeModal }: Props<S>) {
  const [st, setSt] = useState<PhoneFormStatus<S> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const r = await api.status();
      if (!alive) return;
      if (r.ok) {
        setSt(r.data);
        if (r.data.state === "done") {
          toaster.toast({ title, body: r.data.message || "Paired" });
          if (r.data.settings) onDone?.(r.data.settings);
          closeModal?.();
          return;
        }
        if (r.data.state !== "waiting") return;
      }
      timer = setTimeout(poll, 1500);
    };
    api.start().then((r) => {
      if (!alive) return;
      if (!r.ok) return setError(r.error.message);
      setSt(r.data);
      timer = setTimeout(poll, 1500);
    });
    return () => {
      alive = false;
      clearTimeout(timer);
      void api.stop();
    };
  }, []);

  const svg = useMemo(() => (st?.url ? qrSvg(st.url) : null), [st?.url]);
  const closed = st && st.state !== "waiting" && st.state !== "done";
  const short = st?.url?.replace(/^http:\/\//, "");

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ display: "flex", gap: "24px", alignItems: "center" }}>
        <div
          style={{
            width: "220px",
            height: "220px",
            flexShrink: 0,
            background: "#fff",
            borderRadius: "8px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            opacity: closed ? 0.25 : 1,
          }}
        >
          {svg ? (
            <div style={{ width: "100%", height: "100%" }} dangerouslySetInnerHTML={{ __html: svg }} />
          ) : (
            !error && <SteamSpinner />
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: "10px" }}>
          <div style={{ fontSize: "22px", fontWeight: "bold" }}>Pair with your phone</div>
          <div style={{ fontSize: "14px", color: "#b8bcbf", lineHeight: 1.4 }}>
            Scan the code with a phone on the same network, or open this address in its browser. {description}
          </div>
          {short && (
            <div
              style={{
                fontFamily: "monospace",
                fontSize: "20px",
                padding: "8px 12px",
                background: "rgba(255,255,255,0.08)",
                borderRadius: "6px",
                wordBreak: "break-all",
              }}
            >
              {short}
            </div>
          )}
          <div style={{ fontSize: "13px", color: error || closed ? "#ff6b6b" : "#8b929a" }}>
            {error ??
              (closed
                ? st!.state === "expired"
                  ? "This pairing link expired. Close and try again."
                  : st!.state === "locked"
                    ? "Too many wrong addresses were tried, so pairing stopped. Close and try again."
                    : "Pairing stopped."
                : st
                  ? `Waiting for your phone… (closes in ${Math.ceil((st.expires_in ?? 0) / 60)} min)`
                  : "Starting…")}
          </div>
          <Focusable style={{ marginTop: "6px" }}>
            <DialogButton onClick={closeModal}>Cancel</DialogButton>
          </Focusable>
        </div>
      </div>
    </ModalRoot>
  );
}
