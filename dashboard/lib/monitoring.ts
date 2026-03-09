export interface LiveJobState {
  jobId: string;
  phase: string;
  progressPct: number;
  activeTools: string[];
  tokensUsed: number;
  costUsd: number;
  status: string;
  lastEvent: string | null;
}

export interface JobStreamEvent {
  eventType: string;
  jobId: string;
  timestamp: string;
  phase: string;
  message: string;
  toolName: string;
  toolInput: Record<string, unknown> | null;
  toolResult: string;
  progressPct?: number;
  costUsd?: number;
  metadata: Record<string, unknown> | null;
}

const DEFAULT_API_ORIGIN = "http://localhost:18789";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function toNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }

  return fallback;
}

function toProgressPct(value: unknown): number {
  const numeric = toNumber(value, 0);
  const pct = numeric <= 1 ? numeric * 100 : numeric;
  return Math.min(100, Math.max(0, pct));
}

function toText(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number") {
    return String(value);
  }

  return fallback;
}

function getStateContainer(input: unknown): Record<string, unknown> | null {
  if (!isRecord(input)) {
    return null;
  }

  if (isRecord(input.state)) {
    return input.state;
  }

  return input;
}

export function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    return window.location.origin.replace(/\/$/, "");
  }

  return DEFAULT_API_ORIGIN;
}

export function getWebSocketBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }

  return getApiBaseUrl().replace(/^http/, "ws");
}

export function buildJobWebSocketUrl(jobId: string): string {
  return `${getWebSocketBaseUrl()}/ws/jobs/${encodeURIComponent(jobId)}`;
}

export function buildAnalyticsStreamUrl(jobId: string): string {
  return `${getApiBaseUrl()}/api/analytics/stream/${encodeURIComponent(jobId)}`;
}

export function buildActiveJobsUrl(): string {
  return `${getApiBaseUrl()}/api/monitoring/active`;
}

export function normalizeLiveState(input: unknown, fallbackJobId = ""): LiveJobState | null {
  const raw = getStateContainer(input);
  if (!raw) {
    return null;
  }

  const activeToolsRaw =
    (Array.isArray(raw.active_tools) ? raw.active_tools : null) ??
    (Array.isArray(raw.activeTools) ? raw.activeTools : null) ??
    [];

  return {
    jobId: toText(raw.job_id ?? raw.jobId, fallbackJobId) || fallbackJobId,
    phase: toText(raw.phase, "queued").toLowerCase(),
    progressPct: toProgressPct(raw.progress_pct ?? raw.progressPct ?? raw.progress),
    activeTools: activeToolsRaw.map((tool) => toText(tool)).filter(Boolean),
    tokensUsed: toNumber(raw.tokens_used ?? raw.tokensUsed),
    costUsd: toNumber(raw.cost_usd ?? raw.costUsd ?? raw.cost),
    status: toText(raw.status, "running"),
    lastEvent: toText(raw.last_event ?? raw.lastEvent) || null,
  };
}

export function normalizeActiveJobsResponse(payload: unknown): LiveJobState[] {
  if (!isRecord(payload)) {
    return [];
  }

  const rawJobs = payload.jobs;
  const jobs: LiveJobState[] = [];

  if (Array.isArray(rawJobs)) {
    for (const rawJob of rawJobs) {
      const normalized = normalizeLiveState(rawJob);
      if (normalized) {
        jobs.push(normalized);
      }
    }
  } else if (isRecord(rawJobs)) {
    for (const [jobId, rawJob] of Object.entries(rawJobs)) {
      const normalized = normalizeLiveState(rawJob, jobId);
      if (normalized) {
        jobs.push(normalized);
      }
    }
  }

  return jobs.sort((left, right) => {
    const leftTime = left.lastEvent ? Date.parse(left.lastEvent) : 0;
    const rightTime = right.lastEvent ? Date.parse(right.lastEvent) : 0;
    return rightTime - leftTime;
  });
}

export function normalizeStreamEvent(
  eventType: string,
  payload: unknown,
  fallbackJobId = "",
): JobStreamEvent | null {
  let raw = payload;

  if (typeof payload === "string") {
    try {
      raw = JSON.parse(payload) as Record<string, unknown>;
    } catch {
      return {
        eventType,
        jobId: fallbackJobId,
        timestamp: new Date().toISOString(),
        phase: "",
        message: payload,
        toolName: "",
        toolInput: null,
        toolResult: "",
        metadata: null,
      };
    }
  }

  if (!isRecord(raw)) {
    return null;
  }

  return {
    eventType: toText(raw.event_type ?? raw.eventType, eventType) || eventType,
    jobId: toText(raw.job_id ?? raw.jobId, fallbackJobId) || fallbackJobId,
    timestamp: toText(raw.timestamp, new Date().toISOString()),
    phase: toText(raw.phase).toLowerCase(),
    message: toText(raw.message),
    toolName: toText(raw.tool_name ?? raw.toolName),
    toolInput: isRecord(raw.tool_input) ? raw.tool_input : null,
    toolResult: toText(raw.tool_result ?? raw.toolResult),
    progressPct:
      raw.progress_pct !== undefined || raw.progressPct !== undefined
        ? toProgressPct(raw.progress_pct ?? raw.progressPct)
        : undefined,
    costUsd:
      raw.cost_usd !== undefined || raw.costUsd !== undefined
        ? toNumber(raw.cost_usd ?? raw.costUsd)
        : undefined,
    metadata: isRecord(raw.metadata) ? raw.metadata : null,
  };
}

export function reduceStreamEvent(
  current: LiveJobState | null,
  event: JobStreamEvent,
  fallbackJobId: string,
): LiveJobState {
  const next: LiveJobState =
    current
      ? { ...current }
      : normalizeLiveState(
          {
            job_id: event.jobId || fallbackJobId,
            phase: event.phase || "research",
            progress_pct: event.progressPct ?? 0,
            active_tools: [],
            cost_usd: 0,
            tokens_used: 0,
          },
          fallbackJobId,
        )!;

  next.jobId = event.jobId || next.jobId || fallbackJobId;
  next.lastEvent = event.timestamp;

  if (event.phase) {
    next.phase = event.phase;
  }

  if (event.progressPct !== undefined) {
    next.progressPct = event.progressPct;
  }

  if (event.eventType === "tool_call" && event.toolName) {
    if (!next.activeTools.includes(event.toolName)) {
      next.activeTools = [...next.activeTools, event.toolName];
    }
  }

  if (event.eventType === "tool_result" && event.toolName) {
    next.activeTools = next.activeTools.filter((tool) => tool !== event.toolName);
    if (event.costUsd !== undefined) {
      next.costUsd += event.costUsd;
    }
  }

  if (event.eventType === "progress" && event.costUsd !== undefined) {
    next.costUsd = Math.max(next.costUsd, event.costUsd);
  }

  if (event.eventType === "complete") {
    next.status = "completed";
    next.progressPct = 100;
    next.activeTools = [];
    if (event.costUsd !== undefined) {
      next.costUsd = Math.max(next.costUsd, event.costUsd);
    }
  }

  if (event.eventType === "error") {
    next.status = "failed";
  }

  return next;
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

export function formatPhaseLabel(phase: string): string {
  return phase
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function formatTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return "--:--:--";
  }

  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(timestamp);
}
