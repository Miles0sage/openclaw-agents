import type { Span } from '@/types/analytics';

/** Build a tree from flat spans using parent_span_id. */
export function buildTraceTree(spans: Span[]): Span[] {
  const map = new Map<string, Span>();
  const roots: Span[] = [];

  for (const s of spans) {
    map.set(s.span_id, { ...s, children: [] });
  }

  for (const s of map.values()) {
    if (s.parent_span_id && map.has(s.parent_span_id)) {
      map.get(s.parent_span_id)!.children!.push(s);
    } else {
      roots.push(s);
    }
  }

  return roots;
}

/** Get the maximum duration_ms across all spans. */
export function getMaxDurationMs(spans: Span[]): number {
  return spans.reduce((max, s) => Math.max(max, s.duration_ms), 0);
}
