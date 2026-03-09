import type { JobQueueRow, PhaseRow } from "./types";

export const PHASE_ORDER = ["research", "plan", "execute", "review", "deliver"] as const;

export function getApiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 1 ? 3 : 2,
    maximumFractionDigits: value < 1 ? 3 : 2,
  }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

export function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function formatDateTime(value?: string | null): string {
  if (!value) {
    return "No data";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "No data";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds <= 0) {
    return "No data";
  }

  if (seconds < 60) {
    return `${seconds.toFixed(0)}s`;
  }

  const minutes = Math.floor(seconds / 60);
  const remSeconds = Math.round(seconds % 60);
  if (minutes < 60) {
    return `${minutes}m ${remSeconds}s`;
  }

  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `${hours}h ${remMinutes}m`;
}

export function truncateText(value: string, maxLength = 88): string {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength - 1)}…`;
}

export function normalizeStatus(value?: string | null): string {
  const status = (value || "unknown").toLowerCase();
  if (status === "pending") {
    return "queued";
  }
  if (status === "completed") {
    return "done";
  }
  if (status === "error") {
    return "failed";
  }
  return status;
}

export function statusTone(value: string): string {
  const status = normalizeStatus(value);
  if (status === "queued") {
    return "bg-blue-500/15 text-blue-200 ring-blue-400/30";
  }
  if (status === "running") {
    return "bg-amber-500/15 text-amber-200 ring-amber-400/30";
  }
  if (status === "done" || status === "completed") {
    return "bg-emerald-500/15 text-emerald-200 ring-emerald-400/30";
  }
  if (status === "failed") {
    return "bg-rose-500/15 text-rose-200 ring-rose-400/30";
  }
  return "bg-slate-500/15 text-slate-200 ring-slate-400/30";
}

export function humanizeAgentName(agent?: string | null): string {
  if (!agent || agent === "unknown") {
    return "Unassigned";
  }

  return agent
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function mapPhaseName(phase?: string | null): string {
  const normalized = (phase || "").toLowerCase();
  if (normalized === "verify" || normalized === "code_review") {
    return "review";
  }
  if (normalized === "completed") {
    return "deliver";
  }
  return normalized;
}

export function phaseLabel(phase: string): string {
  return phase.replace(/\b\w/g, (match) => match.toUpperCase());
}

export function countJobsSince(rows: JobQueueRow[], days: number): number {
  const threshold = Date.now() - days * 24 * 60 * 60 * 1000;
  return rows.filter((row) => {
    const parsed = Date.parse(row.createdAt);
    return !Number.isNaN(parsed) && parsed >= threshold;
  }).length;
}

export function getActivePhaseLabel(phases: PhaseRow[]): string {
  const active = phases.find((phase) => phase.status === "active");
  if (active) {
    return active.label;
  }

  const latestComplete = [...phases].reverse().find((phase) => phase.status === "complete");
  return latestComplete?.label || "Research";
}
