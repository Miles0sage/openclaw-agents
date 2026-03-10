interface StatCardProps {
  label: string;
  value: string;
  detail: string;
  accent: string;
}

export function StatCard({ label, value, detail, accent }: StatCardProps) {
  return (
    <article className="rounded-3xl border border-white/10 bg-white/[0.03] p-5 shadow-panel">
      <p className={`text-xs font-semibold uppercase tracking-[0.24em] ${accent}`}>{label}</p>
      <h2 className="mt-3 text-3xl font-semibold text-white">{value}</h2>
      <p className="mt-2 text-sm text-slate-400">{detail}</p>
    </article>
  );
}
