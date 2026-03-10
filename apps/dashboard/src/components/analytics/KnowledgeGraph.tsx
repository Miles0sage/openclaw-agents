// @ts-nocheck — D3 force-simulation generics are extremely strict and
// incompatible with the way d3-force mutates link.source/target from string → node.
// Runtime behavior is correct; TS cannot model d3's internal mutation.
import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import type { KgSummary, KgRecommendResponse } from '@/types/analytics';
import { getKgRecommend } from '@/api/analytics';

interface KnowledgeGraphProps {
  summary: KgSummary;
}

export function KnowledgeGraph({ summary }: KnowledgeGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [recommendations, setRecommendations] = useState<KgRecommendResponse | null>(null);

  useEffect(() => {
    if (!summary.tools.length || !svgRef.current) return;

    const width = svgRef.current.clientWidth || 400;
    const height = 400;

    type NodeDatum = d3.SimulationNodeDatum & { id: string; usage_count: number; x?: number; y?: number; fx?: number | null; fy?: number | null };
    type LinkDatum = { source: string; target: string; strength: number };
    const nodes: NodeDatum[] = summary.tools.map((t) => ({ id: t.key, ...t }));
    const links: LinkDatum[] = summary.edges.map((e) => ({ source: e.source, target: e.target, strength: e.strength }));

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        'link',
        d3.forceLink(links as unknown as { source: NodeDatum; target: NodeDatum; strength: number }[]).id((d: NodeDatum) => d.id).distance(80).strength((d: { strength: number }) => d.strength)
      )
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(width / 2, height / 2));

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const g = svg.append('g').attr('width', width).attr('height', height);

    const link = g
      .append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', '#475569')
      .attr('stroke-opacity', 0.8)
      .attr('stroke-width', (d: { strength: number }) => Math.max(1, d.strength * 4));

    const node = g
      .append('g')
      .selectAll('circle')
      .data(nodes)
      .join('circle')
      .attr('r', (d: { usage_count: number }) => 5 + Math.min(20, d.usage_count / 5))
      .attr('fill', '#38bdf8')
      .attr('stroke', '#0ea5e9')
      .call(
        d3
          .drag<SVGCircleElement, NodeDatum>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x ?? 0;
            d.fy = d.y ?? 0;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    const label = g
      .append('g')
      .selectAll('text')
      .data(nodes)
      .join('text')
      .text((d: NodeDatum) => d.id)
      .attr('font-size', 10)
      .attr('fill', '#94a3b8')
      .attr('dx', 8)
      .attr('dy', 4);

    simulation.on('tick', () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const anyLink = link as d3.Selection<SVGLineElement, any, SVGGElement, unknown>;
      anyLink
        .attr('x1', (d) => (d.source as unknown as NodeDatum).x ?? 0)
        .attr('y1', (d) => (d.source as unknown as NodeDatum).y ?? 0)
        .attr('x2', (d) => (d.target as unknown as NodeDatum).x ?? 0)
        .attr('y2', (d) => (d.target as unknown as NodeDatum).y ?? 0);
      node.attr('cx', (d: NodeDatum) => d.x ?? 0).attr('cy', (d: NodeDatum) => d.y ?? 0);
      label.attr('x', (d: NodeDatum) => d.x ?? 0).attr('y', (d: NodeDatum) => d.y ?? 0);
    });

    return () => {
      simulation.stop();
    };
  }, [summary.tools, summary.edges]);

  useEffect(() => {
    if (!selectedAgent) {
      setRecommendations(null);
      return;
    }
    getKgRecommend(selectedAgent).then(setRecommendations).catch(() => setRecommendations(null));
  }, [selectedAgent]);

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 overflow-hidden">
        <h3 className="mb-3 text-sm font-medium text-slate-300">Tool co-occurrence</h3>
        <svg ref={svgRef} className="w-full h-[400px]" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet" />
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
        <h3 className="mb-3 text-sm font-medium text-slate-300">Agent performance</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {summary.agents.map((a) => (
            <div
              key={a.agent_key}
              className={`rounded border p-3 cursor-pointer transition-colors ${
                selectedAgent === a.agent_key ? 'border-sky-500 bg-sky-500/10' : 'border-slate-600 bg-slate-800/30 hover:border-slate-500'
              }`}
              onClick={() => setSelectedAgent(selectedAgent === a.agent_key ? null : a.agent_key)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && setSelectedAgent(selectedAgent === a.agent_key ? null : a.agent_key)}
            >
              <p className="font-mono text-slate-200 text-sm">{a.agent_key}</p>
              <p className="text-xs text-slate-400">Success: {(a.success_rate * 100).toFixed(0)}%</p>
              <p className="text-xs text-slate-400">Avg cost: ${a.avg_cost_usd.toFixed(4)}</p>
              <p className="text-xs text-slate-500 truncate">Tools: {a.favorite_tools.join(', ')}</p>
            </div>
          ))}
        </div>
      </div>

      {recommendations && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 overflow-x-auto">
          <h3 className="mb-3 text-sm font-medium text-slate-300">
            Recommended tool chains — {recommendations.agent_key}
          </h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400 border-b border-slate-600">
                <th className="pb-2 pr-4">Chain</th>
                <th className="pb-2">Score</th>
              </tr>
            </thead>
            <tbody>
              {recommendations.recommendations.map((row, i) => (
                <tr key={i} className="border-b border-slate-700/50">
                  <td className="py-2 pr-4 font-mono text-slate-300">
                    {row.recommended_chain.join(' → ')}
                  </td>
                  <td className="py-2 text-slate-400">{row.score != null ? row.score.toFixed(2) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
