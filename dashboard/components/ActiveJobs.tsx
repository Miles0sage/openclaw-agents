"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  buildActiveJobsUrl,
  formatCurrency,
  formatPhaseLabel,
  normalizeActiveJobsResponse,
  type LiveJobState,
} from "../lib/monitoring";

const POLL_INTERVAL_MS = 5000;

export function ActiveJobs() {
  const [jobs, setJobs] = useState<LiveJobState[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    let inFlightController: AbortController | null = null;

    const loadJobs = async () => {
      inFlightController?.abort();
      const controller = new AbortController();
      inFlightController = controller;

      try {
        const response = await fetch(buildActiveJobsUrl(), {
          signal: controller.signal,
          cache: "no-store",
        });

        if (!response.ok) {
          throw new Error(`Active jobs request failed with ${response.status}.`);
        }

        const payload = (await response.json()) as unknown;
        if (!disposed) {
          setJobs(normalizeActiveJobsResponse(payload));
          setError(null);
        }
      } catch (fetchError) {
        if (fetchError instanceof DOMException && fetchError.name === "AbortError") {
          return;
        }

        if (!disposed) {
          setError(
            fetchError instanceof Error
              ? fetchError.message
              : "Active jobs polling failed.",
          );
        }
      } finally {
        if (!disposed) {
          setIsLoading(false);
        }
      }
    };

    void loadJobs();
    const intervalId = window.setInterval(() => {
      void loadJobs();
    }, POLL_INTERVAL_MS);

    return () => {
      disposed = true;
      inFlightController?.abort();
      window.clearInterval(intervalId);
    };
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Overview</p>
          <h2 className="panel-title">Active jobs</h2>
        </div>
        <span className="badge">{jobs.length} live</span>
      </div>

      {isLoading ? <p className="muted-copy">Loading current job queue…</p> : null}
      {error ? <p className="error-copy">{error}</p> : null}

      {!isLoading && jobs.length === 0 ? (
        <div className="empty-state">
          <p>No active jobs</p>
          <span className="muted-copy">The executor is idle right now.</span>
        </div>
      ) : null}

      <div className="job-list">
        {jobs.map((job) => (
          <Link key={job.jobId} href={`/jobs/${job.jobId}`} className="job-card">
            <div className="job-card-header">
              <div>
                <p className="job-id">{job.jobId}</p>
                <h3>{formatPhaseLabel(job.phase)}</h3>
              </div>
              <span className={`phase-pill phase-pill-${job.status}`}>{job.status}</span>
            </div>

            <div className="progress-track progress-track-compact" aria-hidden="true">
              <div className="progress-fill" style={{ width: `${job.progressPct}%` }} />
            </div>

            <div className="job-meta">
              <span>{Math.round(job.progressPct)}%</span>
              <span>{formatCurrency(job.costUsd)}</span>
              <span>{job.activeTools.length} tools</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
