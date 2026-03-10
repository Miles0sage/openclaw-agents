import { Fragment, useState } from 'react';
import { useRunbook } from '@/hooks/useRunbook';

const severityLabel: Record<string, string> = {
  critical: 'CRITICAL',
  warning: 'WARNING',
  info: 'INFO',
};

export function RunbookPanel() {
  const { entries, loading, error } = useRunbook();
  const [expandedType, setExpandedType] = useState<string | null>(null);

  if (error) return <p className="text-rose-400 text-sm">{error}</p>;
  if (loading) return <p className="text-slate-400 text-sm">Loading runbook…</p>;

  return (
    <div className="space-y-4">
      <p className="text-slate-400 text-sm">Reference: failure types and recommended steps.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-400 border-b border-slate-600">
              <th className="pb-2 pr-4">Failure type</th>
              <th className="pb-2 pr-4">Severity</th>
              <th className="pb-2 pr-4">Title</th>
              <th className="pb-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <Fragment key={entry.failure_type}>
                <tr className="border-b border-slate-700/50">
                  <td className="py-2 pr-4 font-mono text-slate-300">{entry.failure_type}</td>
                  <td className="py-2 pr-4 text-slate-400">{severityLabel[entry.severity] ?? entry.severity}</td>
                  <td className="py-2 pr-4 text-slate-300">{entry.title}</td>
                  <td className="py-2">
                    <button
                      type="button"
                      onClick={() => setExpandedType(expandedType === entry.failure_type ? null : entry.failure_type)}
                      className="rounded border border-slate-600 bg-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-600"
                    >
                      {expandedType === entry.failure_type ? 'Hide' : 'View'}
                    </button>
                  </td>
                </tr>
                {expandedType === entry.failure_type && (
                  <tr>
                    <td colSpan={4} className="pb-3 pt-0">
                      <div className="rounded border border-slate-600 bg-slate-800/50 p-3 text-sm space-y-2">
                        {entry.diagnostic_steps.length > 0 && (
                          <>
                            <p className="text-slate-300 font-medium">Diagnostic steps</p>
                            <ol className="list-decimal list-inside text-slate-400 space-y-1">
                              {entry.diagnostic_steps.map((s, i) => (
                                <li key={i}>{s}</li>
                              ))}
                            </ol>
                          </>
                        )}
                        {entry.remediation.length > 0 && (
                          <>
                            <p className="text-slate-300 font-medium">Remediation</p>
                            <ol className="list-decimal list-inside text-slate-400 space-y-1">
                              {entry.remediation.map((r, i) => (
                                <li key={i}>{r}</li>
                              ))}
                            </ol>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
