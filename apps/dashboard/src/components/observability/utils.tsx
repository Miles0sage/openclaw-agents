export function timeAgoBadge(ts: number | null): JSX.Element | null {
  if (!ts) return null;
  const sec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  const label = sec < 60 ? `${sec}s ago` : sec < 3600 ? `${Math.floor(sec / 60)}m ago` : `${Math.floor(sec / 3600)}h ago`;
  return (
    <span className="inline-flex items-center rounded border border-slate-600 bg-slate-800/60 px-2 py-0.5 text-xs text-slate-400">
      Updated {label}
    </span>
  );
}

export function CardShell({
  title,
  right,
  children,
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-3 card-hover animate-slide-up">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-300">{title}</h3>
        {right}
      </div>
      {children}
    </div>
  );
}

export function SkeletonBlock({ className }: { className: string }) {
  return <div className={`animate-pulse rounded bg-slate-700 ${className}`} aria-hidden />;
}

