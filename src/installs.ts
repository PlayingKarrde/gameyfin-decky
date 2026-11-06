// Polls the worker's job states and turns finished downloads into Steam shortcuts.
// Lives for the whole plugin lifetime (started in definePlugin), not per page.
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import {
  ACTIVE_PHASES,
  InstalledGame,
  JobState,
  dismissJob,
  getGame,
  getInstalled,
  getJobs,
  registerInstalled,
} from "./backend";
import { applyArtwork, pickCompatTool, setCompatTool, upsertShortcut } from "./steam";

type Snapshot = { jobs: JobState[]; installed: InstalledGame[] };

let snapshot: Snapshot = { jobs: [], installed: [] };
const listeners = new Set<(s: Snapshot) => void>();
const finishing = new Set<string>();
const failed = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;
let stopped = true;

function emit() {
  listeners.forEach((l) => l(snapshot));
}

export async function refresh(): Promise<Snapshot> {
  const [j, i] = await Promise.all([getJobs(), getInstalled()]);
  snapshot = { jobs: j.ok ? j.data : snapshot.jobs, installed: i.ok ? i.data : snapshot.installed };
  emit();
  for (const job of snapshot.jobs) {
    if (job.phase === "done" && !job.exe_ambiguous && !finishing.has(job.job_id)) {
      void finishInstall(job);
    }
  }
  return snapshot;
}

async function tick() {
  if (stopped) return;
  try {
    await refresh();
  } catch (e) {
    console.warn("[gameyfin] poll failed", e);
  }
  const busy = snapshot.jobs.some((j) => ACTIVE_PHASES.includes(j.phase));
  if (!stopped) timer = setTimeout(tick, busy ? 1000 : 5000);
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

/** Create/update the Steam shortcut for a finished job and record the install. */
export async function finishInstall(job: JobState, exeRel?: string, manual = false): Promise<void> {
  if (manual && failed.delete(job.job_id)) finishing.delete(job.job_id);
  if (finishing.has(job.job_id) || !job.install_dir) return;
  finishing.add(job.job_id);
  const title = job.title ?? `Game ${job.game_id}`;
  try {
    const rel = exeRel ?? job.exe_candidates?.[0]?.path ?? null;
    const prev = snapshot.installed.find((g) => g.game_id === String(job.game_id));
    if (!rel) {
      await registerInstalled(job.game_id, {
        title, install_dir: job.install_dir, exe: null, appid: prev?.appid ?? null, size: job.installed_bytes ?? null,
      });
      toaster.toast({ title: "Gameyfin", body: `${title} installed, but no .exe was found` });
      await dismissJob(job.job_id);
      return;
    }
    const exe = `${job.install_dir}/${rel}`;
    const startDir = exe.slice(0, exe.lastIndexOf("/"));
    const appId = await upsertShortcut({ name: title, exe, startDir }, prev?.appid);
    const tool = await pickCompatTool(appId);
    if (tool) await setCompatTool(appId, tool);

    const saved = await registerInstalled(job.game_id, {
      title, install_dir: job.install_dir, exe: rel, appid: appId, size: job.installed_bytes ?? null, compat_tool: tool,
    });
    if (!saved.ok) throw new Error(saved.error.message);
    await dismissJob(job.job_id);
    toaster.toast({ title: "Gameyfin", body: `${title} is ready to play` });

    const detail = await getGame(job.game_id);
    if (detail.ok) {
      await applyArtwork(appId, {
        cover: detail.data.cover,
        header: detail.data.header,
        fallbackHero: detail.data.images[0],
      });
    }
  } catch (e) {
    console.error("[gameyfin] finishing install failed", e);
    toaster.toast({ title: "Gameyfin", body: `Couldn't add ${title} to Steam: ${(e as Error).message}` });
    failed.add(job.job_id); // no auto-retry loop; the panel offers "Add to Steam"
  } finally {
    void refresh();
  }
}

export const finishFailed = (jobId: string) => failed.has(jobId);
