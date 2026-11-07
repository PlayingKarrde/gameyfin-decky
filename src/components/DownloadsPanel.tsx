import { ButtonItem, PanelSection, PanelSectionRow, ProgressBarWithInfo, showModal } from "@decky/ui";
import { ACTIVE_PHASES, JobState, cancelInstall, dismissJob, formatBytes } from "../backend";
import { finishFailed, finishInstall, refresh, useInstallState } from "../installs";
import { ExePickerModal } from "./InstallModals";

const PHASE_TEXT: Record<string, string> = {
  queued: "Queued",
  starting: "Starting",
  downloading: "Downloading",
  extracting: "Extracting",
  installing: "Running installer",
  finalizing: "Finishing",
  done: "Adding to Steam",
  error: "Failed",
  cancelled: "Cancelled",
};

function eta(job: JobState): string | undefined {
  if (!job.speed || !job.total || job.phase !== "downloading") return undefined;
  const s = Math.max(0, Math.round((job.total - job.done) / job.speed));
  return s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function JobRow({ job }: { job: JobState }) {
  const active = ACTIVE_PHASES.includes(job.phase);
  const pct = job.total ? Math.min(100, (100 * job.done) / job.total) : undefined;
  const needsExe = job.phase === "done" && job.exe_ambiguous;
  const failedFinish = job.phase === "done" && !job.exe_ambiguous && finishFailed(job.job_id);
  const op =
    job.phase === "error"
      ? job.error ?? "Failed"
      : needsExe
        ? "Choose the executable"
        : `${PHASE_TEXT[job.phase] ?? job.phase}${job.total ? ` · ${formatBytes(job.done)} / ${formatBytes(job.total)}` : ""}${
            job.speed ? ` · ${formatBytes(job.speed)}/s` : ""
          }`;

  return (
    <>
      <PanelSectionRow>
        <ProgressBarWithInfo
          label={`${job.kind === "update" ? "Update: " : ""}${job.title ?? `Game ${job.game_id}`}`}
          nProgress={job.phase === "done" ? 100 : pct}
          indeterminate={active && pct == null}
          sOperationText={op}
          sTimeRemaining={eta(job)}
        />
      </PanelSectionRow>
      {active && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => cancelInstall(job.job_id).then(() => refresh())}>
            Cancel
          </ButtonItem>
        </PanelSectionRow>
      )}
      {(needsExe || failedFinish) && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() =>
              showModal(
                <ExePickerModal
                  installDir={job.install_dir!}
                  title={job.title ?? ""}
                  initial={job.exe_candidates}
                  onPick={(rel) => void finishInstall(job, rel, true)}
                />,
              )
            }
          >
            {needsExe ? "Choose executable" : "Add to Steam"}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {(job.phase === "error" || job.phase === "cancelled") && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => dismissJob(job.job_id).then(() => refresh())}>
            Dismiss
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}

export function DownloadsPanel() {
  const { jobs } = useInstallState();
  if (!jobs.length) return null;
  return (
    <PanelSection title="Downloads">
      {jobs.map((j) => (
        <JobRow key={j.job_id} job={j} />
      ))}
    </PanelSection>
  );
}
