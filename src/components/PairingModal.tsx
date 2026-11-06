import { DialogButton, Focusable, ModalRoot, SteamSpinner } from "@decky/ui";
import { toaster } from "@decky/api";
import qrcode from "qrcode-generator";
import { useEffect, useMemo, useState } from "react";
import { PairingStatus, PublicSettings, getPairingStatus, startPairing, stopPairing } from "../backend";

function qrSvg(text: string): string {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
}

type Props = { onPaired?: (s: PublicSettings) => void; closeModal?: () => void };

/** Shows a QR/short URL served by a short-lived LAN page where the phone pastes the token. */
export function PairingModal({ onPaired, closeModal }: Props) {
  const [st, setSt] = useState<PairingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const r = await getPairingStatus();
      if (!alive) return;
      if (r.ok) {
        setSt(r.data);
        if (r.data.state === "done") {
          toaster.toast({ title: "Gameyfin", body: r.data.message || "Paired" });
          if (r.data.settings) onPaired?.(r.data.settings);
          closeModal?.();
          return;
        }
        if (r.data.state !== "waiting") return;
      }
      timer = setTimeout(poll, 1500);
    };
    startPairing().then((r) => {
      if (!alive) return;
      if (!r.ok) return setError(r.error.message);
      setSt(r.data);
      timer = setTimeout(poll, 1500);
    });
    return () => {
      alive = false;
      clearTimeout(timer);
      void stopPairing();
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
            Scan the code with a phone on the same network, or open this address in its browser. Create a personal
            access token in Gameyfin and paste it on that page.
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
