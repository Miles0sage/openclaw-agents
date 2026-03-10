"use client";

import { useEffect, useRef, useState } from "react";

import { getApiBaseUrl, phaseLabel } from "@/lib/format";

interface LogStreamProps {
  jobId: string;
}

interface LogLine {
  id: string;
  tone: "default" | "tool" | "error" | "phase";
  timestamp: string;
  message: string;
}

const EVENT_TYPES = [
  "connected",
  "phase_change",
  "tool_call",
  "tool_result",
  "progress",
  "error",
  "complete",
] as const;

function toMessage(type: string, payload: Record<string, unknown>): LogLine {
  const timestamp = String(payload.timestamp || new Date().toISOString());
  const id = `${timestamp}:${type}:${String(payload.tool_name || "")}:${String(payload.message || "")}`;

  if (type === "phase_change") {
    return {
      id,
      tone: "phase",
      timestamp,
      message: `phase ${phaseLabel(String(payload.phase || "research"))}`,
    };
  }

  if (type === "tool_call") {
    return {
      id,
      tone: "tool",
      timestamp,
      message: `call ${String(payload.tool_name || "tool")} ${JSON.stringify(payload.tool_input || {})}`,
    };
  }

  if (type === "tool_result") {
    return {
      id,
      tone: "default",
      timestamp,
      message: `result ${String(payload.tool_name || "tool")} ${String(payload.tool_result || "")}`,
    };
  }

  if (type === "error") {
    return {
      id,
      tone: "error",
      timestamp,
      message: String(payload.message || "Job failed"),
    };
  }

  return {
    id,
    tone: "default",
    timestamp,
    message: String(payload.message || "Event received"),
  };
}

export function LogStream({ jobId }: LogStreamProps) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const streamUrl = `${getApiBaseUrl()}/api/analytics/stream/${jobId}`;

  useEffect(() => {
    const source = new EventSource(streamUrl);

    source.onopen = () => setError(null);
    source.onerror = () => setError("Log stream unavailable.");

    const handleEvent = (event: Event) => {
      if (!("data" in event) || typeof event.data !== "string") {
        return;
      }

      try {
        const payload = JSON.parse(event.data) as Record<string, unknown>;
        setLines((current) => [...current, toMessage(event.type, payload)].slice(-500));
      } catch {
        setLines((current) =>
          [
            ...current,
            {
              id: `${Date.now()}:raw`,
              tone: "default" as const,
              timestamp: new Date().toISOString(),
              message: String(event.data),
            },
          ].slice(-500),
        );
      }
    };

    for (const eventType of EVENT_TYPES) {
      source.addEventListener(eventType, handleEvent);
    }

    return () => {
      for (const eventType of EVENT_TYPES) {
        source.removeEventListener(eventType, handleEvent);
      }
      source.close();
    };
  }, [streamUrl]);

  useEffect(() => {
    if (viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [lines]);

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/90 p-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">Live Log</p>
          <h2 className="mt-2 text-2xl font-semibold text-white">SSE stream</h2>
        </div>
      </div>

      <div
        ref={viewportRef}
        className="mt-6 h-[26rem] overflow-auto rounded-2xl border border-white/8 bg-black/40 p-4 font-mono text-sm"
      >
        {lines.length === 0 ? (
          <p className="text-slate-500">No data</p>
        ) : (
          <div className="space-y-3">
            {lines.map((line) => (
              <div key={line.id} className="grid grid-cols-[88px_1fr] gap-3">
                <span className="text-slate-500">{new Date(line.timestamp).toLocaleTimeString()}</span>
                <span
                  className={
                    line.tone === "tool"
                      ? "text-cyan-300"
                      : line.tone === "error"
                        ? "text-rose-300"
                        : line.tone === "phase"
                          ? "text-orange-300"
                          : "text-slate-100"
                  }
                >
                  {line.message}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}
    </section>
  );
}
