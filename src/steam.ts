// Thin wrappers over SteamClient.Apps.* (undocumented; patterns from MoonDeck,
// decky-steamgriddb and protondb-decky). Keep every Steam call in this file.
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

// Custom artwork lives in decky-common (shared with romm-decky).
export { applyArtwork } from "./common/artwork";
