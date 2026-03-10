import type { Alert } from '@/types/alerts';

interface AlertDetailProps {
  alert: Alert;
}

export function AlertDetail({ alert }: AlertDetailProps) {
  return (
    <div className="mt-3 rounded border border-slate-600 bg-slate-800/50 p-3 text-sm space-y-3">
      <p className="text-slate-300 font-medium">Message</p>
      <p className="text-slate-400 whitespace-pre-wrap">{alert.message}</p>
      {alert.diagnostic_steps.length > 0 && (
        <>
          <p className="text-slate-300 font-medium">Diagnostic steps</p>
          <ol className="list-decimal list-inside text-slate-400 space-y-1">
            {alert.diagnostic_steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </>
      )}
      {alert.remediation.length > 0 && (
        <>
          <p className="text-slate-300 font-medium">Remediation</p>
          <ol className="list-decimal list-inside text-slate-400 space-y-1">
            {alert.remediation.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
