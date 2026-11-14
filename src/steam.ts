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

/** One read of an app's details, or null if Steam doesn't answer within timeoutMs. */
function detailsOf(appId: number, timeoutMs = 2000): Promise<any> {
  return new Promise((resolve) => {
    let reg: { unregister(): void } | undefined;
    const timer = setTimeout(() => {
      reg?.unregister();
      resolve(null);
    }, timeoutMs);
    try {
      reg = SteamClient.Apps.RegisterForAppDetails(appId, (d: any) => {
        clearTimeout(timer);
        setTimeout(() => reg?.unregister(), 0);
        resolve(d && Object.keys(d).length ? d : null);
      });
    } catch {
      clearTimeout(timer);
      resolve(null);
    }
  });
}

/**
 * True when Steam would run this shortcut through a compatibility tool (Proton, a runtime) instead
 * of running the exe directly. Steam's November 2026 client (checked 2026-11-14) turned
 * SpecifyCompatTool(appid, "") from "no tool" into "the default tool" (Proton 11), and has no call
 * that clears a per-app choice again. Such shortcuts show either a tool name or an (empty)
 * strCompatExperiment, and fail with "compatibility tool failed" or start Proton. Untouched
 * shortcuts have neither.
 */
export async function compatToolSet(appId: number): Promise<boolean> {
  const d = await detailsOf(appId);
  return !!d && (!!d.strCompatToolName || "strCompatExperiment" in d);
}

export type ShortcutSpec = { name: string; exe: string; startDir: string; launchOptions?: string };

async function createShortcut(spec: ShortcutSpec): Promise<number> {
  const id = await SteamClient.Apps.AddShortcut(spec.name, spec.exe, spec.startDir, "");
  if (typeof id !== "number") throw new Error("Steam did not create the shortcut");
  await waitForDetails(id, (d) => d != null);
  return id;
}

/**
 * Create a shortcut (or update an existing one). Returns the appid, and whether it is a new
 * shortcut (artwork then needs setting again, and the appid recording).
 *
 * ``native``: the exe runs directly, with no compatibility tool. A new shortcut starts that way.
 * An existing one that has a tool set (a native reinstall of a Windows build, or one made by
 * 0.6.4 or earlier on current Steam) can't be cleared, so it is recreated: the new one is made
 * first, and the old one removed only if the new one is clean. Steam gives it a new appid.
 */
export async function upsertShortcut(
  spec: ShortcutSpec,
  existing: number | null | undefined,
  native: boolean,
): Promise<{ appId: number; created: boolean }> {
  let appId = existing && shortcutExists(existing) ? existing : null;
  let created = false;
  if (appId != null && native && (await compatToolSet(appId))) {
    // Keep the user's own launch options when we have none to set (set below; AddShortcut's
    // fourth argument doesn't set them).
    const carried = spec.launchOptions ?? (await detailsOf(appId))?.strLaunchOptions ?? "";
    const fresh = await createShortcut(spec);
    if (await compatToolSet(fresh)) {
      SteamClient.Apps.RemoveShortcut(fresh);
      console.warn("[gameyfin] a new shortcut also has a compat tool; keeping", appId);
    } else {
      SteamClient.Apps.RemoveShortcut(appId);
      appId = fresh;
      created = true;
      spec = { ...spec, launchOptions: carried };
    }
  }
  if (appId == null) {
    appId = await createShortcut(spec);
    created = true;
  }
  SteamClient.Apps.SetShortcutName(appId, spec.name);
  SteamClient.Apps.SetShortcutExe(appId, quote(spec.exe));
  SteamClient.Apps.SetShortcutStartDir(appId, quote(spec.startDir));
  // Only when we have something to say ("" clears ours): never wipe the user's own options.
  if (spec.launchOptions !== undefined) SteamClient.Apps.SetAppLaunchOptions(appId, spec.launchOptions);
  await waitForDetails(appId, (d) => d?.strDisplayName === spec.name, 2000);
  return { appId, created };
}

export async function removeShortcut(appId: number): Promise<void> {
  if (!shortcutExists(appId)) return;
  SteamClient.Apps.RemoveShortcut(appId);
  await waitForDetails(appId, (d) => d == null, 2000);
}

/**
 * Prefer Proton Experimental, then the newest numbered Proton, then anything Proton-ish.
 * Current Steam (2026-11-14) has no GetAvailableCompatTools, so this returns
 * proton_experimental there: it's Valve's, and Steam downloads it on first launch if missing.
 */
export async function pickCompatTool(appId: number): Promise<string> {
  try {
    const tools = (await SteamClient.Apps.GetAvailableCompatTools(appId)) ?? [];
    const names = tools.map((t) => t.strToolName);
    if (names.includes("proton_experimental")) return "proton_experimental";
    const numbered = names
      .filter((n) => /^proton_\d+$/.test(n))
      .sort((a, b) => parseInt(b.slice(7)) - parseInt(a.slice(7)));
    return numbered[0] ?? names.find((n) => n.toLowerCase().includes("proton")) ?? "proton_experimental";
  } catch {
    return "proton_experimental";
  }
}

/** Set a named compat tool. Never pass "": on current Steam that selects the default (Proton). */
export async function setCompatTool(appId: number, tool: string): Promise<void> {
  if (!tool) throw new Error("setCompatTool needs a tool name");
  SteamClient.Apps.SpecifyCompatTool(appId, tool);
  await sleep(200);
}

// ---- artwork ---------------------------------------------------------------

// Custom artwork lives in decky-common (shared with romm-decky).
export { applyArtwork } from "./common/artwork";
