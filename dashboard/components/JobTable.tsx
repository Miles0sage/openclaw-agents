import Link from "next/link";

import {
  formatCurrency,
  formatDateTime,
  humanizeAgentName,
  statusTone,
  truncateText,
} from "@/lib/format";
import type { JobQueueRow } from "@/lib/types";

interface JobTableProps {
  rows: JobQueueRow[];
  emptyMessage?: string;
}

export function JobTable({
  rows,
  emptyMessage = "No jobs are available for this view.",
}: JobTableProps) {
  if (rows.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-white/15 bg-slate-900/40 px-6 py-16 text-center text-sm text-slate-400">
        {emptyMessage}
      </div>
    );
  }

  return (
    <>
      <div className="hidden overflow-hidden rounded-3xl border border-white/10 lg:block">
        <table className="min-w-full divide-y divide-white/10 text-left text-sm">
          <thead className="bg-white/[0.03] text-xs uppercase tracking-[0.22em] text-slate-400">
            <tr>
              <th className="px-4 py-4">Job</th>
              <th className="px-4 py-4">Project</th>
              <th className="px-4 py-4">Task</th>
              <th className="px-4 py-4">Status</th>
              <th className="px-4 py-4">Agent</th>
              <th className="px-4 py-4">Cost</th>
              <th className="px-4 py-4">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 bg-slate-950/40">
            {rows.map((row) => (
              <tr key={row.jobId} className="transition hover:bg-white/[0.03]">
                <td className="px-4 py-4 font-mono text-xs text-cyan-200">
                  <Link href={`/jobs/${row.jobId}`} className="block">
                    {row.jobId}
                  </Link>
                </td>
                <td className="px-4 py-4 text-slate-200">
                  <Link href={`/jobs/${row.jobId}`} className="block">
                    {row.project}
                  </Link>
                </td>
                <td className="px-4 py-4 text-slate-300">
                  <Link href={`/jobs/${row.jobId}`} className="block">
                    {truncateText(row.task, 92)}
                  </Link>
                </td>
                <td className="px-4 py-4">
                  <Link href={`/jobs/${row.jobId}`} className="block">
                    <span
                      className={`inline-flex rounded-full px-3 py-1 text-xs font-medium capitalize ring-1 ${statusTone(
                        row.status,
                      )}`}
                    >
                      {row.status}
                    </span>
                  </Link>
                </td>
                <td className="px-4 py-4 text-slate-300">
                  <Link href={`/jobs/${row.jobId}`} className="block">
                    {humanizeAgentName(row.agent)}
                  </Link>
                </td>
                <td className="px-4 py-4 text-slate-200">
                  <Link href={`/jobs/${row.jobId}`} className="block">
                    {formatCurrency(row.cost)}
                  </Link>
                </td>
                <td className="px-4 py-4 text-slate-400">
                  <Link href={`/jobs/${row.jobId}`} className="block">
                    {formatDateTime(row.createdAt)}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 lg:hidden">
        {rows.map((row) => (
          <Link
            key={row.jobId}
            href={`/jobs/${row.jobId}`}
            className="rounded-3xl border border-white/10 bg-white/[0.03] p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-mono text-xs text-cyan-200">{row.jobId}</p>
                <h3 className="mt-2 text-lg font-semibold text-white">{row.project}</h3>
              </div>
              <span
                className={`inline-flex rounded-full px-3 py-1 text-xs font-medium capitalize ring-1 ${statusTone(
                  row.status,
                )}`}
              >
                {row.status}
              </span>
            </div>
            <p className="mt-3 text-sm text-slate-300">{truncateText(row.task, 128)}</p>
            <div className="mt-4 flex flex-wrap gap-3 text-xs text-slate-400">
              <span>{humanizeAgentName(row.agent)}</span>
              <span>{formatCurrency(row.cost)}</span>
              <span>{formatDateTime(row.createdAt)}</span>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
