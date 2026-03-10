"use client";

import { useEffect, useState } from "react";

import { buildAnalyticsStreamUrl, normalizeStreamEvent, type JobStreamEvent } from "../lib/monitoring";

interface UseSSEOptions {
  enabled?: boolean;
}

interface UseSSEResult {
  data: JobStreamEvent | null;
  isConnected: boolean;
  error: string | null;
}

const STREAM_EVENTS = [
  "connected",
  "phase_change",
  "tool_call",
  "tool_result",
  "progress",
  "error",
  "complete",
  "timeout",
] as const;

export function useSSE(jobId: string, options: UseSSEOptions = {}): UseSSEResult {
  const [data, setData] = useState<JobStreamEvent | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = options.enabled ?? true;

  useEffect(() => {
    if (!jobId || typeof window === "undefined") {
      return;
    }

    if (!enabled) {
      setIsConnected(false);
      setError(null);
      return;
    }

    const source = new EventSource(buildAnalyticsStreamUrl(jobId));

    const handleStreamEvent = (event: Event) => {
      const payload = "data" in event ? event.data : null;
      if (typeof payload !== "string") {
        return;
      }

      const normalized = normalizeStreamEvent(event.type, payload, jobId);
      if (!normalized) {
        return;
      }

      setData(normalized);
      if (event.type !== "error") {
        setError(null);
      }
    };

    source.onopen = () => {
      setIsConnected(true);
      setError(null);
    };

    source.onerror = () => {
      setIsConnected(false);
      setError("SSE connection failed.");
    };

    for (const eventName of STREAM_EVENTS) {
      source.addEventListener(eventName, handleStreamEvent);
    }

    return () => {
      for (const eventName of STREAM_EVENTS) {
        source.removeEventListener(eventName, handleStreamEvent);
      }
      source.close();
      setIsConnected(false);
    };
  }, [enabled, jobId]);

  return { data, isConnected, error };
}
