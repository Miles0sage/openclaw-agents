"use client";

import {
  formatCurrency,
  formatNumber,
  formatPhaseLabel,
  type LiveJobState,
} from "../lib/monitoring";

interface LiveJobProgressProps {
  state: LiveJobState | null;
  error?: string | null;
}

export function LiveJobProgress({ state, error }: LiveJobProgressProps) {
  if (!state) {
    return (
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Job State</p>
            <h2 className="panel-title">Awaiting telemetry</h2>
          </div>
        </div>
        <p className="muted-copy">
          Waiting for the first live event from the monitor endpoint.
        </p>
        {error ? <p className="error-copy">{error}</p> : null}
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Job State</p>
          <h2 className="panel-title">{formatPhaseLabel(state.phase)}</h2>
        </div>
        <span className={`phase-pill phase-pill-${state.status}`}>
          <span className="phase-pill-pulse" />
          {state.status}
        </span>
      </div>

      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(state.progressPct)}
      >
        <div className="progress-fill" style={{ width: `${state.progressPct}%` }} />
      </div>

      <div className="metric-grid">
        <article className="metric-card">
          <span className="metric-label">Progress</span>
          <strong className="metric-value">{Math.round(state.progressPct)}%</strong>
        </article>
        <article className="metric-card">
          <span className="metric-label">Cost</span>
          <strong className="metric-value">{formatCurrency(state.costUsd)}</strong>
        </article>
        <article className="metric-card">
          <span className="metric-label">Tokens</span>
          <strong className="metric-value">{formatNumber(state.tokensUsed)}</strong>
        </article>
      </div>

      <div className="tools-block">
        <div className="tools-header">
          <p className="eyebrow">Active Tools</p>
          <span className="muted-copy">{state.activeTools.length} running</span>
        </div>
        {state.activeTools.length ? (
          <div className="tool-list">
            {state.activeTools.map((tool) => (
              <span key={tool} className="tool-chip">
                {tool}
              </span>
            ))}
          </div>
        ) : (
          <p className="muted-copy">No tools are currently executing.</p>
        )}
      </div>

      {error ? <p className="error-copy">{error}</p> : null}
    </section>
  );
}
