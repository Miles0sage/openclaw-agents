import { ActiveJobs } from "../components/ActiveJobs";

const transportCards = [
  {
    title: "WebSocket primary",
    copy: "Per-job state updates land over /ws/jobs/{job_id} with reconnect backoff and heartbeats.",
  },
  {
    title: "SSE fallback",
    copy: "The dashboard can keep progressing and stream logs even when the socket transport drops.",
  },
  {
    title: "Polling overview",
    copy: "The landing page refreshes the active job queue every 5 seconds through /api/monitoring/active.",
  },
];

export default function DashboardHomePage() {
  return (
    <div className="page-stack">
      <header className="hero">
        <div>
          <p className="eyebrow">OpenClaw Dashboard</p>
          <h1 className="hero-title">Realtime fleet view for active jobs</h1>
          <p className="hero-copy">
            Track current execution phases, tool activity, burn rate, and jump
            directly into a live job stream when something needs attention.
          </p>
        </div>
        <span className="badge">Live monitoring</span>
      </header>

      <div className="overview-grid">
        <ActiveJobs />

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Transport Stack</p>
              <h2 className="panel-title">How the telemetry flows</h2>
            </div>
          </div>

          <div className="surface-grid">
            {transportCards.map((card) => (
              <article key={card.title} className="mini-stat">
                <h3>{card.title}</h3>
                <p className="muted-copy">{card.copy}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
