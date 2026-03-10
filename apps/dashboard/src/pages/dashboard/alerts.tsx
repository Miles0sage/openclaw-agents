import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AlertsPanel } from '@/components/AlertsPanel';
import { RunbookPanel } from '@/components/RunbookPanel';

export function AlertsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = useMemo<'alerts' | 'runbook'>(() => {
    const t = searchParams.get('tab');
    return t === 'runbook' ? 'runbook' : 'alerts';
  }, [searchParams]);

  const [tab, setTab] = useState<'alerts' | 'runbook'>(initialTab);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  const setTabAndUrl = (next: 'alerts' | 'runbook') => {
    setTab(next);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('tab', next);
    setSearchParams(nextParams, { replace: true });
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-100">Alerts & Runbook</h1>
      <div className="flex gap-2 border-b border-slate-700 pb-2">
        <button
          type="button"
          onClick={() => setTabAndUrl('alerts')}
          className={`px-3 py-1.5 rounded text-sm font-medium ${
            tab === 'alerts' ? 'bg-sky-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
          }`}
        >
          Alerts
        </button>
        <button
          type="button"
          onClick={() => setTabAndUrl('runbook')}
          className={`px-3 py-1.5 rounded text-sm font-medium ${
            tab === 'runbook' ? 'bg-sky-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
          }`}
        >
          Runbook
        </button>
      </div>
      {tab === 'alerts' && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
          <AlertsPanel />
        </div>
      )}
      {tab === 'runbook' && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
          <RunbookPanel />
        </div>
      )}
    </div>
  );
}
