import { useState, useEffect, useCallback } from 'react';
import { getRunbook } from '@/api/alerts';
import type { RunbookEntry } from '@/types/alerts';

export function useRunbook() {
  const [entries, setEntries] = useState<RunbookEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setError(null);
    try {
      const data = await getRunbook();
      setEntries(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load runbook');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { entries, loading, error, refetch };
}
