import { useState, useCallback, useRef } from 'react';
import { getStreamUrl } from '@/api/analytics';
import type { LivePhase } from '@/types/analytics';

type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';

interface ToolCallLog {
  tool: string;
  input_preview: string;
  result_ok: boolean;
  at: number;
}

const PHASE_PCT: Record<LivePhase, number> = {
  RESEARCH: 10,
  PLAN: 25,
  EXECUTE: 60,
  VERIFY: 80,
  DELIVER: 95,
};

export function LiveJobMonitor() {
  const [jobId, setJobId] = useState('');
  const [status, setStatus] = useState<ConnectionStatus>('idle');
  const [phase, setPhase] = useState<LivePhase | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [toolCalls, setToolCalls] = useState<ToolCallLog[]>([]);
  const [costUsd, setCostUsd] = useState<number | null>(null);
  const [done, setDone] = useState<{ success: boolean; final_cost_usd: number } | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (status === 'connected' || status === 'connecting') {
      setStatus('disconnected');
    }
  }, [status]);

  const connect = useCallback(() => {
    const id = jobId.trim();
    if (!id) return;

    disconnect();
    setStatus('connecting');
    setPhase(null);
    setProgressPct(0);
    setToolCalls([]);
    setCostUsd(null);
    setDone(null);

    const url = getStreamUrl(id);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => setStatus('connected');

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const type = data.type ?? data.event ?? 'unknown';

        if (type === 'phase' || data.phase) {
          const p = data.phase as LivePhase;
          setPhase(p);
          setProgressPct(typeof data.progress_pct === 'number' ? data.progress_pct : PHASE_PCT[p] ?? 0);
        } else if (type === 'tool_call' || data.tool) {
          setToolCalls((prev) => [
            ...prev,
            {
              tool: data.tool ?? '?',
              input_preview: data.input_preview ?? '',
              result_ok: Boolean(data.result_ok),
              at: Date.now(),
            },
          ]);
        } else if (type === 'cost' || data.accumulated_usd != null) {
          setCostUsd(Number(data.accumulated_usd));
        } else if (type === 'done' || data.success != null) {
          setDone({
            success: Boolean(data.success),
            final_cost_usd: Number(data.final_cost_usd ?? costUsd ?? 0),
          });
          es.close();
          eventSourceRef.current = null;
          setStatus('disconnected');
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      setStatus('error');
      es.close();
      eventSourceRef.current = null;
    };

    es.addEventListener('close', () => {
      setStatus('disconnected');
      es.close();
      eventSourceRef.current = null;
    });
  }, [jobId, disconnect]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          placeholder="Job ID"
          className="rounded border border-slate-600 bg-slate-800 px-3 py-2 text-slate-100 placeholder-slate-500 w-48 font-mono text-sm"
          onKeyDown={(e) => e.key === 'Enter' && connect()}
        />
        <button
          type="button"
          onClick={connect}
          disabled={status === 'connecting' || !jobId.trim()}
          className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          Connect
        </button>
        {(status === 'disconnected' || status === 'error') && (
          <button
            type="button"
            onClick={connect}
            className="rounded border border-slate-500 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700"
          >
            Reconnect
          </button>
        )}
        <span
          className={`text-sm ${
            status === 'connected' ? 'text-emerald-400' : status === 'error' ? 'text-rose-400' : 'text-slate-400'
          }`}
        >
          {status === 'idle' && 'Enter job ID and connect'}
          {status === 'connecting' && 'Connecting…'}
          {status === 'connected' && '● Live'}
          {status === 'disconnected' && 'Disconnected'}
          {status === 'error' && 'Connection error'}
        </span>
      </div>

      {done && (
        <div className="rounded-lg border border-slate-600 bg-slate-800/50 p-4">
          <p className="font-medium text-slate-200">
            Job finished: {done.success ? 'Success' : 'Failed'}
          </p>
          <p className="text-sm text-slate-400">Final cost: ${done.final_cost_usd.toFixed(4)}</p>
        </div>
      )}

      {(status === 'connected' || status === 'connecting' || phase || progressPct > 0) && !done && (
        <>
          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
            <div className="mb-2 flex justify-between text-sm">
              <span className="text-slate-400">Phase</span>
              <span className="text-slate-200">{phase ?? '—'}</span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-700 overflow-hidden">
              <div
                className="h-full bg-sky-500 transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="mt-1 text-xs text-slate-500">{progressPct}%</div>
          </div>

          {costUsd != null && (
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
              <span className="text-slate-400 text-sm">Accumulated cost </span>
              <span className="font-mono text-slate-100">${costUsd.toFixed(4)}</span>
            </div>
          )}

          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 max-h-64 overflow-auto">
            <h3 className="mb-2 text-sm font-medium text-slate-300">Tool calls</h3>
            {toolCalls.length === 0 ? (
              <p className="text-slate-500 text-sm">Waiting for events…</p>
            ) : (
              <ul className="space-y-1 text-sm font-mono">
                {toolCalls.map((tc, i) => (
                  <li key={i} className="flex items-center gap-2 text-slate-300">
                    <span className={tc.result_ok ? 'text-emerald-500' : 'text-rose-400'}>
                      {tc.result_ok ? '✓' : '✗'}
                    </span>
                    <span className="text-sky-400">{tc.tool}</span>
                    {tc.input_preview && (
                      <span className="truncate text-slate-500 max-w-[200px]" title={tc.input_preview}>
                        {tc.input_preview}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
