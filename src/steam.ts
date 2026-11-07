// Thin wrappers over SteamClient.Apps.* (undocumented; patterns from MoonDeck,
// decky-steamgriddb and protondb-decky). Keep every Steam call in this file.
import { ArtPlan, dropArtwork, getArtwork, getImageChunk } from "./backend";

const ASSET = { capsule: 0, hero: 1, logo: 2, header: 3, icon: 4 } as const;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function appStore(): any {
  return (window as any).appStore ?? null;
}

export function shortcutExists(appId: number): boolean {
  try {
    return !!appStore()?.GetAppOverviewByAppID(appId);
  } catch {
    return false;
  }
}

/** Resolve once app details satisfy pred, or false after timeoutMs. */
function waitForDetails(appId: number, pred: (d: any) => boolean, timeoutMs = 3000): Promise<boolean> {
  return new Promise((resolve) => {
    let done = false;
    let reg: { unregister(): void } | undefined;
    const finish = (v: boolean) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      setTimeout(() => reg?.unregister(), 0);
      resolve(v);
    };
    const timer = setTimeout(() => finish(false), timeoutMs);
    try {
      reg = SteamClient.Apps.RegisterForAppDetails(appId, (d: any) => {
        if (pred(d && Object.keys(d).length ? d : null)) finish(true);
      });
    } catch {
      finish(false);
    }
  });
}

const quote = (p: string) => `"${p}"`;

export type ShortcutSpec = { name: string; exe: string; startDir: string; launchOptions?: string };

/** Create a shortcut (or update an existing one). Returns the appid. */
export async function upsertShortcut(spec: ShortcutSpec, existing?: number | null): Promise<number> {
  let appId = existing && shortcutExists(existing) ? existing : null;
  if (appId == null) {
    const id = await SteamClient.Apps.AddShortcut(spec.name, spec.exe, spec.startDir, spec.launchOptions ?? "");
    if (typeof id !== "number") throw new Error("Steam did not create the shortcut");
    appId = id;
    await waitForDetails(appId, (d) => d != null);
  }
  SteamClient.Apps.SetShortcutName(appId, spec.name);
  SteamClient.Apps.SetShortcutExe(appId, quote(spec.exe));
  SteamClient.Apps.SetShortcutStartDir(appId, quote(spec.startDir));
  // Only when we have something to say ("" clears ours): never wipe the user's own options.
  if (spec.launchOptions !== undefined) SteamClient.Apps.SetAppLaunchOptions(appId, spec.launchOptions);
  await waitForDetails(appId, (d) => d?.strDisplayName === spec.name, 2000);
  return appId;
}

export async function removeShortcut(appId: number): Promise<void> {
  if (!shortcutExists(appId)) return;
  SteamClient.Apps.RemoveShortcut(appId);
  await waitForDetails(appId, (d) => d == null, 2000);
}

/** Prefer Proton Experimental, then the newest numbered Proton, then anything Proton-ish. */
export async function pickCompatTool(appId: number): Promise<string | null> {
  try {
    const tools = (await SteamClient.Apps.GetAvailableCompatTools(appId)) ?? [];
    const names = tools.map((t) => t.strToolName);
    if (names.includes("proton_experimental")) return "proton_experimental";
    const numbered = names
      .filter((n) => /^proton_\d+$/.test(n))
      .sort((a, b) => parseInt(b.slice(7)) - parseInt(a.slice(7)));
    return numbered[0] ?? names.find((n) => n.toLowerCase().includes("proton")) ?? null;
  } catch {
    return "proton_experimental";
  }
}

/** tool "" clears the compat tool (native Linux games run directly). */
export async function setCompatTool(appId: number, tool: string): Promise<void> {
  SteamClient.Apps.SpecifyCompatTool(appId, tool);
  await sleep(200);
}

// ---- artwork ---------------------------------------------------------------

async function fetchOriginal(url: string): Promise<string | null> {
  const info = await getArtwork(url);
  if (!info.ok) return null;
  const parts: string[] = [];
  for (let i = 0; i < info.data.chunks; i++) {
    const c = await getImageChunk(url, i);
    if (!c.ok) return null;
    parts.push(c.data);
  }
  return `data:${info.data.content_type};base64,${parts.join("")}`;
}

/** Re-encode via canvas so Steam always gets PNG (covers webp etc.). Returns bare base64. */
async function toPngBase64(dataUrl: string): Promise<string> {
  if (dataUrl.startsWith("data:image/png;")) return dataUrl.slice(dataUrl.indexOf(",") + 1);
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve(i);
    i.onerror = () => reject(new Error("decode failed"));
    i.src = dataUrl;
  });
  const c = document.createElement("canvas");
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  c.getContext("2d")!.drawImage(img, 0, 0);
  const out = c.toDataURL("image/png");
  return out.slice(out.indexOf(",") + 1);
}

async function setArt(appId: number, url: string | null | undefined, types: number[]): Promise<boolean> {
  if (!url) return false;
  const src = await fetchOriginal(url);
  if (!src) return false;
  const b64 = await toPngBase64(src);
  for (const t of types) {
    await SteamClient.Apps.ClearCustomArtworkForApp(appId, t as any).catch(() => undefined);
    await sleep(300); // Clear resolves before it's actually cleared
    await SteamClient.Apps.SetCustomArtworkForApp(appId, b64, "png", t as any);
  }
  return true;
}

// A new shortcut's logo isn't drawn (Steam shows the title as text) until a logo position
// exists in grid/<appid>.json. This is Steam's own default, as its "Adjust logo" UI saves it.
const DEFAULT_LOGO_POSITION = { nVersion: 1, logoPosition: { pinnedPosition: "BottomLeft", nWidthPct: 50, nHeightPct: 50 } };

/** Best effort: failures are logged, never thrown. Slots without a URL are left alone. */
export async function applyArtwork(appId: number, plan: ArtPlan): Promise<void> {
  // Group by URL so an image used for two slots (e.g. Gameyfin's header) is fetched once.
  const byUrl = new Map<string, number[]>();
  const slots: [string | null, number][] = [
    [plan.capsule, ASSET.capsule],
    [plan.wide, ASSET.header],
    [plan.hero, ASSET.hero],
    [plan.logo, ASSET.logo],
  ];
  for (const [url, t] of slots) if (url) byUrl.set(url, [...(byUrl.get(url) ?? []), t]);
  for (const [url, types] of byUrl) {
    try {
      if ((await setArt(appId, url, types)) && types.includes(ASSET.logo)) {
        await SteamClient.Apps.SetCustomLogoPositionForApp(appId, JSON.stringify(DEFAULT_LOGO_POSITION));
      }
    } catch (e) {
      console.warn("[gameyfin] artwork failed", url, e);
    }
    void dropArtwork(url).catch(() => undefined);
  }
}
