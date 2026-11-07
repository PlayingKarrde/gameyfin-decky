// Polls the worker's job states and turns finished downloads into Steam shortcuts.
// Also tracks install status (missing files/shortcuts, server updates).
// Lives for the whole plugin lifetime (started in definePlugin), not per page.
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import {
  ACTIVE_PHASES,
  InstallStatus,
  InstalledGame,
  JobState,
  dismissJob,
  getArtPlan,
  getInstallStatus,
  isWindowsExe,
  getInstalled,
  getJobs,
  registerInstalled,
  updateGame,
} from "./backend";
import { applyArtwork, pickCompatTool, setCompatTool, shortcutExists, upsertShortcut } from "./steam";

type Snapshot = { jobs: JobState[]; installed: InstalledGame[]; status: InstallStatus[] };

let snapshot: Snapshot = { jobs: [], installed: [], status: [] };
const listeners = new Set<(s: Snapshot) => void>();
const finishing = new Set<string>();
const failed = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;
let stopped = true;
let ticking = false; // a tick is awaiting refresh()
let rerun = false; // kick() arrived mid-tick: tick again right after
let lastStatusAt = 0;
let statusInFlight: Promise<void> | null = null;
const STATUS_EVERY_MS = 15 * 60 * 1000;

function emit() {
  listeners.forEach((l) => l(snapshot));
}

export async function refresh(): Promise<Snapshot> {
  const [j, i] = await Promise.all([getJobs(), getInstalled()]);
  snapshot = { ...snapshot, jobs: j.ok ? j.data : snapshot.jobs, installed: i.ok ? i.data : snapshot.installed };
  emit();
  for (const job of snapshot.jobs) {
    if (job.phase === "done" && !job.exe_ambiguous && !finishing.has(job.job_id)) {
      void finishInstall(job);
    }
  }
  return snapshot;
}

/** Re-check installed games against disk and the server (a few HTTP calls; not on every tick). */
export function refreshStatus(): Promise<void> {
  if (statusInFlight) return statusInFlight;
  statusInFlight = (async () => {
    try {
      const r = await getInstallStatus();
      if (r.ok) {
        snapshot = { ...snapshot, status: r.data };
        emit();
      }
    } catch (e) {
      console.warn("[gameyfin] status check failed", e);
    } finally {
      lastStatusAt = Date.now();
      statusInFlight = null;
    }
  })();
  return statusInFlight;
}

async function tick() {
  if (stopped) return;
  if (ticking) {
    rerun = true;
    return;
  }
  ticking = true;
  timer = null;
  try {
    await refresh();
    if (Date.now() - lastStatusAt > STATUS_EVERY_MS) void refreshStatus();
  } catch (e) {
    console.warn("[gameyfin] poll failed", e);
  } finally {
    ticking = false;
  }
  if (stopped) return;
  const busy = snapshot.jobs.some((j) => ACTIVE_PHASES.includes(j.phase));
  const delay = rerun ? 0 : busy ? 1000 : 5000;
  rerun = false;
  if (timer) clearTimeout(timer);
  timer = setTimeout(tick, delay);
}

export function startPolling() {
  if (!stopped) return;
  stopped = false;
  void tick();
}

export function stopPolling() {
  stopped = true;
  if (timer) clearTimeout(timer);
  timer = null;
}

/** Poke the poller now (e.g. right after starting an install). */
export function kick() {
  if (timer) clearTimeout(timer);
  if (!stopped) void tick();
}

export function useInstallState(): Snapshot {
  const [s, setS] = useState(snapshot);
  useEffect(() => {
    listeners.add(setS);
    setS(snapshot);
    return () => void listeners.delete(setS);
  }, []);
  return s;
}

export const getSnapshot = () => snapshot;

// ---- derived state ------------------------------------------------------------

export type Health = "ok" | "files_missing" | "unmarked" | "shortcut_missing";

/** What's wrong with an install, if anything. Shortcut presence is checked live in Steam. */
export function healthOf(inst: InstalledGame, st?: InstallStatus): Health {
  if (st?.files === "missing") return "files_missing";
  if (st?.files === "unmarked") return "unmarked";
  if (inst.exe && (!inst.appid || !shortcutExists(inst.appid))) return "shortcut_missing";
  return "ok";
}

export const statusFor = (s: Snapshot, gameId: string) => s.status.find((x) => x.game_id === String(gameId));

export const activeJobFor = (s: Snapshot, gameId: string) =>
  s.jobs.find((j) => String(j.game_id) === String(gameId) && (ACTIVE_PHASES.includes(j.phase) || j.phase === "done"));

// ---- Steam shortcut ------------------------------------------------------------

/** Steam launch options: the dependency wrapper and/or GOG's game arguments. "" clears a
 *  wrapper we set before (its script may be gone); undefined leaves the user's own alone. */
function launchOptionsFor(installDir: string, extra: Partial<InstalledGame>, prev?: InstalledGame): string | undefined {
  const parts: string[] = [];
  if (extra.deps_wrapper) parts.push(`/bin/bash "${installDir}/${extra.deps_wrapper}" %command%`);
  if (extra.launch_args) parts.push(extra.launch_args);
  if (parts.length) return parts.join(" ");
  return prev?.deps_wrapper ? "" : undefined;
}

/** Create or update the shortcut (+ compat tool) and record it. Returns the appid. */
async function addShortcut(
  gameId: string,
  title: string,
  installDir: string,
  rel: string,
  prevAppId: number | null | undefined,
  extra: Partial<InstalledGame> = {},
): Promise<number> {
  const exe = `${installDir}/${rel}`;
  const startDir = extra.work_dir ? `${installDir}/${extra.work_dir}` : exe.slice(0, exe.lastIndexOf("/"));
  const prev = snapshot.installed.find((g) => g.game_id === String(gameId));
  const launchOptions = launchOptionsFor(installDir, extra, prev);
  const appId = await upsertShortcut({ name: title, exe, startDir, launchOptions }, prevAppId);
  let tool: string | null = null;
  if (isWindowsExe(rel)) {
    tool = await pickCompatTool(appId);
    if (tool) await setCompatTool(appId, tool);
  } else {
    await setCompatTool(appId, ""); // native: clear Proton (e.g. a reinstall that switched builds)
  }
  const saved = await registerInstalled(gameId, {
    ...extra,
    title,
    install_dir: installDir,
    exe: rel,
    appid: appId,
    compat_tool: tool,
  });
  if (!saved.ok) throw new Error(saved.error.message);
  return appId;
}

export async function applyGameArtwork(gameId: string, appId: number): Promise<boolean> {
  const plan = await getArtPlan(gameId);
  if (!plan.ok) {
    console.warn("[gameyfin] art plan failed", plan.error);
    return false;
  }
  await applyArtwork(appId, plan.data);
  return true;
}

/** Create/update the Steam shortcut for a finished job and record the install. */
export async function finishInstall(job: JobState, exeRel?: string, manual = false): Promise<void> {
  if (manual && failed.delete(job.job_id)) finishing.delete(job.job_id);
  if (finishing.has(job.job_id) || !job.install_dir) return;
  finishing.add(job.job_id);
  const title = job.title ?? `Game ${job.game_id}`;
  const isUpdate = job.kind === "update";
  const extra: Partial<InstalledGame> = {
    size: job.installed_bytes ?? null,
    server_file_size: job.server_file_size ?? null,
    deps_wrapper: job.deps_wrapper ?? null,
    deps: job.deps ?? null,
  };
  // GOG's launch arguments / working dir belong to its primary exe only.
  const primary = job.exe_candidates?.[0]?.path;
  try {
    const rel = exeRel ?? primary ?? null;
    if (rel && rel === primary && (job.launch_args || job.work_dir)) {
      extra.launch_args = job.launch_args || null;
      extra.work_dir = job.work_dir || null;
    }
    const prev = snapshot.installed.find((g) => g.game_id === String(job.game_id));
    if (!rel) {
      await registerInstalled(job.game_id, {
        ...extra, title, install_dir: job.install_dir, exe: null, appid: prev?.appid ?? null,
      });
      toaster.toast({ title: "Gameyfin", body: `${title} installed, but no .exe was found` });
      await dismissJob(job.job_id);
      return;
    }
    const hadShortcut = !!prev?.appid && shortcutExists(prev.appid);
    const appId = await addShortcut(job.game_id, title, job.install_dir, rel, prev?.appid, extra);
    await dismissJob(job.job_id);
    const deps = job.deps?.length ? ` The first launch also installs ${job.deps.join(", ")}, so it takes longer.` : "";
    toaster.toast({ title: "Gameyfin", body: (isUpdate ? `${title} updated.` : `${title} is ready to play.`) + deps });
    for (const w of job.warnings ?? []) toaster.toast({ title: `Gameyfin: ${title}`, body: w });
    // An update keeps the existing shortcut and its artwork (which the user may have customised).
    if (!(isUpdate && hadShortcut)) await applyGameArtwork(job.game_id, appId);
  } catch (e) {
    console.error("[gameyfin] finishing install failed", e);
    toaster.toast({ title: "Gameyfin", body: `Couldn't add ${title} to Steam: ${(e as Error).message}` });
    failed.add(job.job_id); // no auto-retry loop; the panel offers "Add to Steam"
  } finally {
    void refresh().then(() => refreshStatus());
  }
}

export const finishFailed = (jobId: string) => failed.has(jobId);

/** Recreate a shortcut the user removed in Steam, for an install whose files are intact. */
export async function readdToSteam(inst: InstalledGame, exeRel?: string): Promise<void> {
  const rel = exeRel ?? inst.exe;
  if (!rel) throw new Error("No executable chosen");
  const keepLaunch: Partial<InstalledGame> = {
    deps_wrapper: inst.deps_wrapper ?? null,
    deps: inst.deps ?? null,
    ...(rel === inst.exe ? { launch_args: inst.launch_args, work_dir: inst.work_dir } : {}),
  };
  const appId = await addShortcut(inst.game_id, inst.title, inst.install_dir, rel, inst.appid, keepLaunch);
  toaster.toast({ title: "Gameyfin", body: `${inst.title} is back in your library` });
  void refresh();
  await applyGameArtwork(inst.game_id, appId);
}

export async function startUpdate(inst: InstalledGame): Promise<boolean> {
  const r = await updateGame(inst.game_id);
  toaster.toast({ title: "Gameyfin", body: r.ok ? `Updating ${inst.title}` : `Update failed: ${r.error.message}` });
  if (r.ok) kick();
  return r.ok;
}
