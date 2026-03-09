import { formatDateTime, formatDuration } from "@/lib/format";
import type { PhaseRow } from "@/lib/types";

interface PhaseTimelineProps {
  phases: PhaseRow[];
}

export function PhaseTimeline({ phases }: PhaseTimelineProps) {
  return (
    <section className="rounded-3xl border border-white/10 bg-white/[0.03] p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-orange-300">
            Timeline
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-white">Execution phases</h2>
        </div>
      </div>

      <div className="grid gap-4">
        {phases.map((phase) => {
          const markerClass =
            phase.status === "complete"
              ? "bg-emerald-400"
              : phase.status === "active"
                ? "bg-orange-400 ring-8 ring-orange-400/20"
                : "bg-slate-700";

          return (
            <div
              key={phase.key}
              className="grid gap-4 rounded-2xl border border-white/8 bg-slate-950/40 p-4 md:grid-cols-[auto_1fr_auto]"
            >
              <div className="flex items-center gap-3">
                <span className={`h-3 w-3 rounded-full ${markerClass}`} />
                <span className="font-medium text-white">{phase.label}</span>
              </div>
              <div className="grid gap-1 text-sm text-slate-400">
                <span>Started: {formatDateTime(phase.startedAt)}</span>
                <span>Completed: {formatDateTime(phase.completedAt)}</span>
              </div>
              <div className="text-sm text-slate-300">{formatDuration(phase.durationSec)}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
