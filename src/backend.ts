import { callable } from "@decky/api";

export type ApiError = { message: string; status: number | null; code: string | null };
export type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError };

export type PublicSettings = {
  server_url: string;
  has_token: boolean;
  custom_install_dir: string;
};

export type ConnectionInfo = {
  ok: boolean;
  server_version: string | null;
  game_count: number | null;
  download_providers: string[];
  username: string | null;
  token_kind: "personal" | "service";
};

export type GameSummary = {
  id: string;
  title: string;
  platforms: string[];
  release: string | null;
  file_size: number | null;
  cover: string | null;
};

export type GameDetail = GameSummary & {
  summary: string | null;
  header: string | null;
  images: string[];
  genres: string[];
  developers: string[];
  publishers: string[];
  critic_rating: number | null;
  user_rating: number | null;
};

export type GamePage = { items: GameSummary[]; page: number; size: number; total: number };

export const getSettings = callable<[], Result<PublicSettings>>("get_settings");
export const saveSettings = callable<[server_url: string, token: string | null], Result<PublicSettings>>(
  "save_settings",
);
export const testConnection = callable<[server_url: string | null, token: string | null], Result<ConnectionInfo>>(
  "test_connection",
);
export const listGames = callable<[page: number, size: number, query: string, library_id: string], Result<GamePage>>(
  "list_games",
);
export type Library = { id: string; name: string };
export const listLibraries = callable<[], Result<Library[]>>("list_libraries");
export const getGame = callable<[game_id: string], Result<GameDetail>>("get_game");
export type ImageInfo = { thumb: string } | { content_type: string; size: number; chunks: number };
export const getImage = callable<[image_url: string], Result<ImageInfo>>("get_image");
export const getImageChunk = callable<[image_url: string, index: number], Result<string>>("get_image_chunk");
export const saveThumbnail = callable<[image_url: string, data_url: string], Result<null>>("save_thumbnail");

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function platformLabel(p: string): string {
  const map: Record<string, string> = { PC_MICROSOFT_WINDOWS: "Windows", LINUX: "Linux", MAC: "macOS" };
  return map[p] ?? p.replace(/_/g, " ").toLowerCase();
}

// ---- install ---------------------------------------------------------------

export type InstallTarget = { id: string; label: string; path: string; free: number | null };
export type ExeCandidate = {
  path: string;
  size: number;
  depth: number;
  name_match: boolean;
  kind?: "windows" | "linux";
};

/** Windows binaries run under Proton; anything else is a native Linux launcher. */
export const isWindowsExe = (rel: string) => /\.(exe|bat|msi)$/i.test(rel);
export type JobPhase =
  | "queued"
  | "starting"
  | "downloading"
  | "extracting"
  | "installing"
  | "finalizing"
  | "done"
  | "error"
  | "cancelled";
export type JobState = {
  job_id: string;
  game_id: string;
  title: string | null;
  phase: JobPhase;
  done: number;
  total: number | null;
  speed?: number;
  error?: string;
  install_dir?: string;
  installed_bytes?: number;
  exe_candidates?: ExeCandidate[];
  exe_ambiguous?: boolean;
  kind?: "install" | "update";
  server_file_size?: number | null;
  launch_args?: string;
  work_dir?: string;
};
export type InstalledGame = {
  game_id: string;
  title: string;
  install_dir: string;
  exe: string | null;
  appid: number | null;
  size: number | null;
  compat_tool?: string | null;
  server_file_size?: number | null;
  launch_args?: string | null;
  work_dir?: string | null;
  installed_at: number;
};

/** From get_install_status: local file health plus server-side update info. */
export type InstallStatus = {
  game_id: string;
  files: "ok" | "missing" | "unmarked";
  update_available: boolean;
  server_missing: boolean;
  server_size: number | null;
  summary: GameSummary;
  error: string | null;
};

export const ACTIVE_PHASES: JobPhase[] = [
  "queued",
  "starting",
  "downloading",
  "extracting",
  "installing",
  "finalizing",
];

export const getInstallTargets = callable<[], Result<InstallTarget[]>>("get_install_targets");
export const setCustomInstallDir = callable<[path: string], Result<PublicSettings>>("set_custom_install_dir");
export const startInstall = callable<[game_id: string, target_path: string], Result<{ job_id: string }>>(
  "start_install",
);
export const getJobs = callable<[], Result<JobState[]>>("get_jobs");
export const cancelInstall = callable<[job_id: string], Result<null>>("cancel_install");
export const dismissJob = callable<[job_id: string], Result<null>>("dismiss_job");
export const listExecutables = callable<[install_dir: string, title: string], Result<ExeCandidate[]>>(
  "list_executables",
);
export const registerInstalled = callable<[game_id: string, record: Partial<InstalledGame>], Result<InstalledGame>>(
  "register_installed",
);
export const getInstalled = callable<[], Result<InstalledGame[]>>("get_installed");
export const uninstallGame = callable<[game_id: string, remove_prefix: boolean], Result<{ prefix_removed: boolean }>>(
  "uninstall_game",
);
export const updateGame = callable<[game_id: string], Result<{ job_id: string }>>("update_game");
export const getInstallStatus = callable<[], Result<InstallStatus[]>>("get_install_status");
export const forgetInstalled = callable<[game_id: string], Result<null>>("forget_installed");
export const prefixExists = callable<[appid: number], Result<boolean>>("prefix_exists");
export const getArtwork = callable<[image_url: string], Result<{ content_type: string; size: number; chunks: number }>>(
  "get_artwork",
);

// ---- phone pairing -----------------------------------------------------------

export type PairingStatus = {
  state: "waiting" | "done" | "expired" | "stopped" | "locked";
  url?: string;
  code?: string;
  message?: string;
  expires_in?: number;
  settings?: PublicSettings;
};
export const startPairing = callable<[], Result<PairingStatus>>("start_pairing");
export const getPairingStatus = callable<[], Result<PairingStatus>>("get_pairing_status");
export const stopPairing = callable<[], Result<null>>("stop_pairing");
