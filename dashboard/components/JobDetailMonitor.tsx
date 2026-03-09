"use client";

import { useEffect, useState } from "react";

import { useSSE } from "../hooks/useSSE";
import { useWebSocket } from "../hooks/useWebSocket";
import { reduceStreamEvent, type LiveJobState } from "../lib/monitoring";
import { ConnectionIndicator } from "./ConnectionIndicator";
import { LiveJobProgress } from "./LiveJobProgress";
import { LogStream } from "./LogStream";

interface JobDetailMonitorProps {
  jobId: string;
}

export function JobDetailMonitor({ jobId }: JobDetailMonitorProps) {
  const websocket = useWebSocket(jobId);
  const sseFallback = useSSE(jobId, { enabled: !websocket.isConnected });
  const [liveState, setLiveState] = useState<LiveJobState | null>(null);

  useEffect(() => {
    setLiveState(null);
  }, [jobId]);

  useEffect(() => {
    if (websocket.data) {
      setLiveState(websocket.data);
    }
  }, [websocket.data]);

  useEffect(() => {
    if (!sseFallback.data) {
      return;
    }

    setLiveState((current) => reduceStreamEvent(current, sseFallback.data!, jobId));
  }, [jobId, sseFallback.data]);

  const transport = websocket.isConnected
    ? "websocket"
    : sseFallback.isConnected
      ? "sse"
      : "offline";
  const connectionError =
    transport === "offline" ? websocket.error ?? sseFallback.error : null;

  return (
    <div className="page-stack">
      <header className="hero">
        <div>
          <p className="eyebrow">Job Detail</p>
          <h1 className="hero-title">Live monitor for {jobId}</h1>
          <p className="hero-copy">
            WebSocket is preferred for state updates. SSE stays ready as the
            fallback transport when the socket is unavailable.
          </p>
        </div>
        <ConnectionIndicator connected={transport !== "offline"} transport={transport} />
      </header>

      <div className="detail-grid">
        <LiveJobProgress state={liveState} error={connectionError} />
        <LogStream jobId={jobId} />
      </div>
    </div>
  );
}
