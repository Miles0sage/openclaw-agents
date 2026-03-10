import { useAlerts } from '@/hooks/useAlerts';
import { Link } from 'react-router-dom';

export function AlertsBadge() {
  const { criticalUnackCount } = useAlerts(
    { severity: 'critical', limit: 100 },
    30_000
  );

  if (criticalUnackCount === 0) return null;

  return (
    <Link
      to="/dashboard/alerts"
      className="shrink-0 flex items-center gap-1 rounded bg-rose-500/20 px-2 py-0.5 text-rose-400 text-xs font-medium hover:bg-rose-500/30"
    >
      <span className="h-2 w-2 rounded-full bg-rose-500" aria-hidden />
      {criticalUnackCount}
    </Link>
  );
}
