import { useState, useEffect, useCallback } from 'react';
import { getAlerts, acknowledgeAlert } from '@/api/alerts';
import type { Alert } from '@/types/alerts';
import type { AlertsParams } from '@/api/alerts';

export function useAlerts(params: AlertsParams = {}, pollIntervalMs = 30_000) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setError(null);
    try {
      const data = await getAlerts(params);
      setAlerts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  }, [params.limit, params.severity, params.job_id]);

  useEffect(() => {
    refetch();
    const id = setInterval(refetch, pollIntervalMs);
    return () => clearInterval(id);
  }, [refetch, pollIntervalMs]);

  const acknowledge = useCallback(async (alertId: string) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === alertId ? { ...a, acknowledged: true } : a))
    );
    try {
      await acknowledgeAlert(alertId);
    } catch {
      setAlerts((prev) =>
        prev.map((a) => (a.id === alertId ? { ...a, acknowledged: false } : a))
      );
    }
  }, []);

  const criticalUnackCount = alerts.filter(
    (a) => a.severity === 'critical' && !a.acknowledged
  ).length;

  return { alerts, loading, error, refetch, acknowledge, criticalUnackCount };
}
