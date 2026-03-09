"use client";

interface ConnectionIndicatorProps {
  connected: boolean;
  transport: "websocket" | "sse" | "offline";
}

export function ConnectionIndicator({
  connected,
  transport,
}: ConnectionIndicatorProps) {
  const label =
    transport === "websocket"
      ? "WebSocket"
      : transport === "sse"
        ? "SSE fallback"
        : "Disconnected";

  return (
    <div className="connection-indicator" role="status" aria-live="polite">
      <span
        className={`status-dot ${connected ? "status-dot-online" : "status-dot-offline"}`}
        aria-hidden="true"
      />
      <span>{label}</span>
    </div>
  );
}
