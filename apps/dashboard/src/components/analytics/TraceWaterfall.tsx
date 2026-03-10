import { useState } from 'react';
import type { Span } from '@/types/analytics';
import { buildTraceTree, getMaxDurationMs } from '@/lib/traceTree';

interface TraceWaterfallProps {
  trace: { trace_id: string; job_id: string; spans: Span[] };
}

function SpanRow({
  span,
  depth,
  maxMs,
  defaultExpanded = true,
}: {
  span: Span;
  depth: number;
  maxMs: number;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const hasChildren = span.children && span.children.length > 0;
  const widthPct = maxMs ? Math.min(100, (span.duration_ms / maxMs) * 100) : 0;

  return (
    <div className="w-full min-w-0">
      <div
        className="flex items-center gap-2 py-1 text-sm hover:bg-slate-700/50 rounded px-1"
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
      >
        <button
          type="button"
          className="shrink-0 w-5 h-5 flex items-center justify-center text-slate-400 hover:text-slate-200"
          onClick={() => setExpanded((e) => !e)}
          aria-label={expanded ? 'Collapse' : 'Expand'}
        >
          {hasChildren ? (expanded ? '▼' : '▶') : '·'}
        </button>
        <span className="shrink-0 font-mono text-slate-300 truncate max-w-[200px]" title={span.name}>
          {span.name}
        </span>
        <span className="shrink-0 text-slate-500 text-xs">{span.duration_ms}ms</span>
        <div className="flex-1 min-w-0 h-4 bg-slate-700 rounded overflow-hidden">
          <div
            className="h-full bg-sky-500/80 rounded"
            style={{ width: `${widthPct}%` }}
            title={`${span.duration_ms}ms`}
          />
        </div>
      </div>
      {hasChildren && expanded && (
        <div className="border-l border-slate-600 ml-2">
          {span.children!.map((c) => (
            <SpanRow
              key={c.span_id}
              span={c}
              depth={depth + 1}
              maxMs={maxMs}
              defaultExpanded={true}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function collectAllSpans(spans: Span[]): Span[] {
  const out: Span[] = [];
  function visit(s: Span) {
    out.push(s);
    s.children?.forEach(visit);
  }
  spans.forEach(visit);
  return out;
}

export function TraceWaterfall({ trace }: TraceWaterfallProps) {
  const flatSpans = trace.spans.some((s) => s.children?.length) ? collectAllSpans(trace.spans) : trace.spans;
  const tree = buildTraceTree(flatSpans);
  const maxMs = getMaxDurationMs(flatSpans);

  if (tree.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 text-slate-400">
        No spans in this trace.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 overflow-x-auto">
      <div className="mb-2 text-xs text-slate-400">
        Trace: {trace.trace_id} · Job: {trace.job_id}
      </div>
      <div className="space-y-0 min-w-[400px]">
        {tree.map((root) => (
          <SpanRow key={root.span_id} span={root} depth={0} maxMs={maxMs} />
        ))}
      </div>
    </div>
  );
}
