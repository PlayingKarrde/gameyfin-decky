import { DialogButton, Dropdown, Focusable, Navigation, SteamSpinner, TextField, showModal } from "@decky/ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GameSummary, InstallStatus, InstalledGame, Library, formatBytes, listGames, listLibraries } from "../backend";
import { healthOf, useInstallState } from "../installs";
import { Cover } from "../common/Cover";
import { GameModal } from "./GameModal";

export const LIBRARY_ROUTE = "/gameyfin";
const PAGE_SIZE = 50;

export type LibraryTab = "all" | "installed" | "updates";
let nextTab: LibraryTab = "all";

/** Open the full-screen library, optionally on a given tab. */
export function openLibrary(tab: LibraryTab = "all") {
  nextTab = tab;
  Navigation.Navigate(LIBRARY_ROUTE);
  Navigation.CloseSideMenus();
}

// Steam's footer (button hints) overlays the bottom ~50px of the screen.
const FOOTER = 56;
const css = `
.gf-card { border-radius: 6px; padding: 4px; transition: transform 80ms ease-out, background 80ms;
  scroll-margin: 16px 0 ${FOOTER + 16}px; }
.gf-card.gf-focus { background: rgba(255,255,255,0.12); transform: scale(1.04); outline: 2px solid #1a9fff; }
`;

type Badge = { text: string; color: string } | null;

function badgeFor(inst: InstalledGame | undefined, st: InstallStatus | undefined): Badge {
  if (!inst) return null;
  const h = healthOf(inst, st);
  if (h !== "ok") return { text: "Needs attention", color: "#ffb84d" };
  if (st?.update_available) return { text: "Update", color: "#1a9fff" };
  return { text: "Installed", color: "#59bf40" };
}

export function LibraryPage() {
  const [tab, setTab] = useState<LibraryTab>(() => {
    const t = nextTab;
    nextTab = "all";
    return t;
  });
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [libraryId, setLibraryId] = useState("");
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [items, setItems] = useState<GameSummary[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);
  const sentinel = useRef<HTMLDivElement>(null);
  const snap = useInstallState();

  useEffect(() => {
    listLibraries().then((r) => r.ok && setLibraries(r.data));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(async (q: string, lib: string, p: number) => {
    const id = ++reqId.current;
    setLoading(true);
    setError(null);
    const r = await listGames(p, PAGE_SIZE, q, lib).catch((e) => ({
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

  // New search or library -> reset to first page (server-backed "All" tab only).
  useEffect(() => {
    if (tab !== "all") return;
    setItems([]);
    setTotal(null);
    load(debounced, libraryId, 0);
  }, [tab, debounced, libraryId, load]);

  // Installed/Updates come from local records + the last status check, filtered locally.
  const local = useMemo(() => {
    if (tab === "all") return null;
    const q = debounced.toLowerCase();
    return snap.installed
      .map((inst) => {
        const st = snap.status.find((s) => s.game_id === inst.game_id);
        const summary: GameSummary = st?.summary ?? {
          id: inst.game_id,
          title: inst.title,
          platforms: [],
          release: null,
          file_size: inst.size,
          cover: null,
        };
        return { summary, inst, st };
      })
      .filter(({ inst, st }) => tab === "installed" || (st?.update_available && healthOf(inst, st) === "ok"))
      .filter(({ summary }) => !q || summary.title.toLowerCase().includes(q))
      .sort((a, b) => a.summary.title.localeCompare(b.summary.title))
      .map((x) => x.summary);
  }, [tab, debounced, snap]);

  const shown = local ?? items;
  const hasMore = tab === "all" && total != null && items.length < total;

  // Infinite scroll: fetch next page when the sentinel nears the viewport.
  useEffect(() => {
    const el = sentinel.current;
    // Stop on error: otherwise each failed page flips `loading` and immediately retries, forever.
    if (!el || !hasMore || loading || error) return;
    const io = new IntersectionObserver((e) => e[0].isIntersecting && load(debounced, libraryId, page + 1), {
      rootMargin: "600px",
    });
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, loading, error, page, debounced, libraryId, load]);

  const open = (g: GameSummary) => showModal(<GameModal game={g} />);

  const updates = snap.installed.filter((inst) => {
    const st = snap.status.find((s) => s.game_id === inst.game_id);
    return st?.update_available && healthOf(inst, st) === "ok";
  }).length;
  const tabs: [LibraryTab, string][] = [
    ["all", "All games"],
    ["installed", `Installed (${snap.installed.length})`],
    ...(updates || tab === "updates" ? [["updates", `Updates (${updates})`] as [LibraryTab, string]] : []),
  ];
  const count = tab === "all" ? total : shown.length;

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
        {count != null ? `Gameyfin · ${count} game${count === 1 ? "" : "s"}` : "Gameyfin"}
      </div>
      <Focusable style={{ display: "flex", alignItems: "center", gap: "16px", paddingBottom: "12px" }}>
        <div style={{ flex: 1 }}>
          <TextField value={query} onChange={(e) => setQuery(e.target.value)} bShowClearAction />
        </div>
        <DialogButton style={{ width: "120px", minWidth: 0 }} onClick={() => Navigation.NavigateBack()}>
          Back
        </DialogButton>
      </Focusable>
      <Focusable style={{ display: "flex", alignItems: "center", gap: "10px", paddingBottom: "12px" }}>
        {tabs.map(([id, label]) => (
          <DialogButton
            key={id}
            onClick={() => setTab(id)}
            style={{
              width: "auto",
              minWidth: 0,
              padding: "6px 16px",
              background: tab === id ? "#1a9fff" : undefined,
              color: tab === id ? "#fff" : undefined,
            }}
          >
            {label}
          </DialogButton>
        ))}
        {tab === "all" && libraries.length > 1 && (
          <div style={{ marginLeft: "auto", minWidth: "200px" }}>
            <Dropdown
              rgOptions={[{ data: "", label: "All libraries" }, ...libraries.map((l) => ({ data: l.id, label: l.name }))]}
              selectedOption={libraryId}
              onChange={(o) => setLibraryId(o.data)}
            />
          </div>
        )}
      </Focusable>

      {tab === "all" && error && (
        <div style={{ color: "#ff6b6b", padding: "16px 0" }}>
          {error}
          {error.includes("not set") ? (
            " — configure the server in the Gameyfin quick-access panel."
          ) : (
            <DialogButton
              style={{ width: "120px", minWidth: 0, marginTop: "10px" }}
              onClick={() => load(debounced, libraryId, items.length ? page + 1 : 0)}
            >
              Retry
            </DialogButton>
          )}
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
        {shown.map((g) => {
          const inst = snap.installed.find((i) => i.game_id === g.id);
          const badge = badgeFor(inst, snap.status.find((s) => s.game_id === g.id));
          return (
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
              <div style={{ fontSize: "11px", color: "#8b929a", whiteSpace: "nowrap" }}>
                {formatBytes(g.file_size)}
                {badge && <span style={{ color: badge.color }}> · {badge.text}</span>}
              </div>
            </Focusable>
          );
        })}
      </Focusable>

      <div ref={sentinel} style={{ height: "1px" }} />
      {tab === "all" && loading && (
        <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
          <SteamSpinner />
        </div>
      )}
      {count === 0 && !(tab === "all" && (loading || error)) && (
        <div style={{ color: "#8b929a", padding: "24px 0" }}>
          {debounced
            ? `No games match “${debounced}”.`
            : tab === "installed"
              ? "No games installed yet."
              : tab === "updates"
                ? "Everything is up to date."
                : "The library is empty."}
        </div>
      )}
    </div>
  );
}
