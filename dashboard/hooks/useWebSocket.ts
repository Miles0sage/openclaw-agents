"use client";

import { useEffect, useRef, useState } from "react";

import { buildJobWebSocketUrl, normalizeLiveState, type LiveJobState } from "../lib/monitoring";

interface UseWebSocketResult {
  data: LiveJobState | null;
  isConnected: boolean;
  error: string | null;
}

const PING_INTERVAL_MS = 25000;

export function useWebSocket(jobId: string): UseWebSocketResult {
  const [data, setData] = useState<LiveJobState | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const pingTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);

  useEffect(() => {
    if (!jobId || typeof window === "undefined") {
      return;
    }

    let disposed = false;

    const clearTimers = () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }

      if (pingTimerRef.current !== null) {
        window.clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
      }
    };

    const disconnect = () => {
      clearTimers();

      if (socketRef.current) {
        socketRef.current.onopen = null;
        socketRef.current.onclose = null;
        socketRef.current.onerror = null;
        socketRef.current.onmessage = null;
        socketRef.current.close();
        socketRef.current = null;
      }
    };

    const scheduleReconnect = () => {
      const delayMs = Math.min(1000 * 2 ** reconnectAttemptRef.current, 30000);
      reconnectAttemptRef.current += 1;

      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delayMs);
    };

    const connect = () => {
      if (disposed) {
        return;
      }

      const socket = new WebSocket(buildJobWebSocketUrl(jobId));
      socketRef.current = socket;

      socket.onopen = () => {
        if (disposed) {
          return;
        }

        reconnectAttemptRef.current = 0;
        setIsConnected(true);
        setError(null);

        if (pingTimerRef.current !== null) {
          window.clearInterval(pingTimerRef.current);
        }

        pingTimerRef.current = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send("ping");
          }
        }, PING_INTERVAL_MS);
      };

      socket.onmessage = (message) => {
        if (disposed) {
          return;
        }

        try {
          const parsed = JSON.parse(message.data) as unknown;
          const normalized = normalizeLiveState(parsed, jobId);
          if (normalized) {
            setData(normalized);
          }
        } catch {
          setError("Received an invalid WebSocket payload.");
        }
      };

      socket.onerror = () => {
        if (!disposed) {
          setError("WebSocket connection failed.");
        }
      };

      socket.onclose = (event) => {
        if (disposed) {
          return;
        }

        clearTimers();
        setIsConnected(false);
        setError(event.reason || "WebSocket disconnected.");
        scheduleReconnect();
      };
    };

    setData(null);
    setIsConnected(false);
    setError(null);
    connect();

    return () => {
      disposed = true;
      disconnect();
      setIsConnected(false);
    };
  }, [jobId]);

  return { data, isConnected, error };
}
