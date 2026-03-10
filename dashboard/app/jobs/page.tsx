import { JobTable } from "@/components/JobTable";
import { JobsFilter } from "@/components/JobsFilter";
import { buildQueueRows, fetchAnalyticsJobs, fetchWorkflowJobs } from "@/lib/api";
import { normalizeStatus } from "@/lib/format";

interface JobsPageProps {
  searchParams: Promise<{
    status?: string;
  }>;
}

export default async function JobsPage({ searchParams }: JobsPageProps) {
  const { status } = await searchParams;
  const [analyticsJobs, workflowJobs] = await Promise.all([
    fetchAnalyticsJobs(50),
    fetchWorkflowJobs(50),
  ]);

  const rows = buildQueueRows(workflowJobs, analyticsJobs);
  const filteredRows =
    status && status !== "all"
      ? rows.filter((row) => normalizeStatus(row.status) === normalizeStatus(status))
      : rows;

  return (
    <div className="space-y-8">
      <section className="rounded-[2rem] border border-white/10 bg-white/[0.03] px-6 py-7 shadow-panel">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-orange-300">
              Job Queue
            </p>
            <h2 className="mt-3 text-4xl font-semibold text-white">Queue and delivery status</h2>
            <p className="mt-3 max-w-3xl text-slate-400">
              The richer queue metadata comes from `/api/jobs`. Analytics data is merged in
              where it exists, and missing fields stay visible as empty data rather than
              disappearing from the table.
            </p>
          </div>
          <JobsFilter />
        </div>
      </section>

      <section className="rounded-[2rem] border border-white/10 bg-white/[0.03] p-6">
        <JobTable rows={filteredRows} emptyMessage="No data" />
      </section>
    </div>
  );
}
