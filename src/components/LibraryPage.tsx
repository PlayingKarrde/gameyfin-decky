import { DialogButton, Focusable, Navigation, SteamSpinner, TextField, showModal } from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { GameSummary, formatBytes, listGames } from "../backend";
import { Cover } from "./Cover";
import { GameModal } from "./GameModal";

export const LIBRARY_ROUTE = "/gameyfin";
const PAGE_SIZE = 50;

// Steam's footer (button hints) overlays the bottom ~50px of the screen.
const FOOTER = 56;
const css = `
.gf-card { border-radius: 6px; padding: 4px; transition: transform 80ms ease-out, background 80ms;
  scroll-margin: 16px 0 ${FOOTER + 16}px; }
.gf-card.gf-focus { background: rgba(255,255,255,0.12); transform: scale(1.04); outline: 2px solid #1a9fff; }
`;

export function LibraryPage() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [items, setItems] = useState<GameSummary[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);
  const sentinel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(async (q: string, p: number) => {
    const id = ++reqId.current;
    setLoading(true);
    setError(null);
    const r = await listGames(p, PAGE_SIZE, q).catch((e) => ({
      ok: false as const,
      error: { message: String(e), status: null, code: null },
    }));
    if (id !== reqId.current) return; // a newer search superseded this one
    setLoading(false);
    if (!r.ok) {
      setError(r.error.message);
      return;
    }
    setItems((prev) => (p === 0 ? r.data.items : [...prev, ...r.data.items]));
    setTotal(r.data.total);
    setPage(p);
  }, []);

  // New search -> reset to first page.
  useEffect(() => {
    setItems([]);
    setTotal(null);
    load(debounced, 0);
  }, [debounced, load]);

  const hasMore = total != null && items.length < total;

  // Infinite scroll: fetch next page when the sentinel nears the viewport.
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasMore || loading) return;
    const io = new IntersectionObserver((e) => e[0].isIntersecting && load(debounced, page + 1), {
      rootMargin: "600px",
    });
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, loading, page, debounced, load]);

  const open = (g: GameSummary) => showModal(<GameModal game={g} />);

  return (
    <div
      style={{
        marginTop: "40px",
        height: "calc(100vh - 40px)",
        boxSizing: "border-box",
        overflowY: "auto",
        padding: `0 24px ${FOOTER + 24}px`,
      }}
    >
      <style>{css}</style>
      <div style={{ padding: "12px 0 6px", fontSize: "14px", color: "#b8bcbf" }}>
        {total != null ? `Gameyfin · ${total} game${total === 1 ? "" : "s"}` : "Gameyfin"}
      </div>
      <Focusable style={{ display: "flex", alignItems: "center", gap: "16px", paddingBottom: "12px" }}>
        <div style={{ flex: 1 }}>
          <TextField
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            bShowClearAction
          />
        </div>
        <DialogButton style={{ width: "120px", minWidth: 0 }} onClick={() => Navigation.NavigateBack()}>
          Back
        </DialogButton>
      </Focusable>

      {error && (
        <div style={{ color: "#ff6b6b", padding: "16px 0" }}>
          {error}
          {error.includes("not set") && " — configure the server in the Gameyfin quick-access panel."}
        </div>
      )}

      <Focusable
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
          gap: "14px",
          padding: "8px 4px", // room for the scaled focus outline
        }}
      >
        {items.map((g) => (
          <Focusable
            key={g.id}
            className="gf-card"
            focusClassName="gf-focus"
            noFocusRing
            onActivate={() => open(g)}
            onClick={() => open(g)}
          >
            <Cover url={g.cover} title={g.title} />
            <div
              style={{
                marginTop: "6px",
                fontSize: "13px",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {g.title}
            </div>
            <div style={{ fontSize: "11px", color: "#8b929a" }}>{formatBytes(g.file_size)}</div>
          </Focusable>
        ))}
      </Focusable>

      <div ref={sentinel} style={{ height: "1px" }} />
      {loading && (
        <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
          <SteamSpinner />
        </div>
      )}
      {!loading && total === 0 && !error && (
        <div style={{ color: "#8b929a", padding: "24px 0" }}>
          {debounced ? `No games match “${debounced}”.` : "The library is empty."}
        </div>
      )}
    </div>
  );
}
