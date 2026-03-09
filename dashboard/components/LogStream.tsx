"use client";

import { useEffect, useRef, useState } from "react";

import { useSSE } from "../hooks/useSSE";
import { formatPhaseLabel, formatTimestamp, type JobStreamEvent } from "../lib/monitoring";

interface LogStreamProps {
  jobId: string;
}

interface LogLine {
  id: string;
  timestamp: string;
  message: string;
  tone: "default" | "tool" | "error" | "phase";
}

function summarizeToolInput(input: Record<string, unknown> | null): string {
  if (!input) {
    return "";
  }

  const serialized = JSON.stringify(input);
  return serialized.length > 120 ? `${serialized.slice(0, 117)}...` : serialized;
}

function toLogLine(event: JobStreamEvent): LogLine {
  const id = [
    event.timestamp,
    event.eventType,
    event.toolName,
    event.message,
    event.toolResult.slice(0, 32),
  ]
    .filter(Boolean)
    .join(":");

  switch (event.eventType) {
    case "phase_change":
      return {
        id,
        timestamp: event.timestamp,
        message: `phase ${formatPhaseLabel(event.phase)}`,
        tone: "phase",
      };
    case "tool_call":
      return {
        id,
        timestamp: event.timestamp,
        message: `call ${event.toolName} ${summarizeToolInput(event.toolInput)}`.trim(),
        tone: "tool",
      };
    case "tool_result":
      return {
        id,
        timestamp: event.timestamp,
        message: `result ${event.toolName} ${event.toolResult}`.trim(),
        tone: "default",
      };
    case "error":
      return {
        id,
        timestamp: event.timestamp,
        message: event.message || "job failed",
        tone: "error",
      };
    case "complete":
      return {
        id,
        timestamp: event.timestamp,
        message: event.message || "job completed",
        tone: "default",
      };
    default:
      return {
        id,
        timestamp: event.timestamp,
        message: event.message || "stream update received",
        tone: "default",
      };
  }
}

export function LogStream({ jobId }: LogStreamProps) {
  const { data, isConnected, error } = useSSE(jobId);
  const [lines, setLines] = useState<LogLine[]>([]);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!data) {
      return;
    }

    setLines((current) => {
      const next = [...current, toLogLine(data)];
      return next.slice(-500);
    });
  }, [data]);

  useEffect(() => {
    if (viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [lines]);

  return (
    <section className="panel panel-terminal">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Live Log</p>
          <h2 className="panel-title">Execution stream</h2>
        </div>
        <span className="badge">{isConnected ? "Streaming" : "Waiting"}</span>
      </div>

      <div ref={viewportRef} className="log-console" role="log" aria-live="polite">
        {lines.length === 0 ? (
          <p className="log-line">
            <span className="log-time">--:--:--</span>
            <span className="log-message">waiting for stream events…</span>
          </p>
        ) : null}

        {lines.map((line) => (
          <p key={line.id} className={`log-line log-line-${line.tone}`}>
            <span className="log-time">{formatTimestamp(line.timestamp)}</span>
            <span className="log-message">{line.message}</span>
          </p>
        ))}
      </div>

      {error ? <p className="error-copy">{error}</p> : null}
    </section>
  );
}
