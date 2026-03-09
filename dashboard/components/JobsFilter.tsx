"use client";

import { useRouter, useSearchParams } from "next/navigation";

const OPTIONS = ["all", "queued", "running", "done", "failed"];

export function JobsFilter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const value = searchParams.get("status") || "all";

  return (
    <label className="inline-flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-sm text-slate-300">
      <span>Status</span>
      <select
        className="bg-transparent text-white outline-none"
        value={value}
        onChange={(event) => {
          const params = new URLSearchParams(searchParams.toString());
          if (event.target.value === "all") {
            params.delete("status");
          } else {
            params.set("status", event.target.value);
          }
          router.push(`/jobs${params.toString() ? `?${params.toString()}` : ""}`);
        }}
      >
        {OPTIONS.map((option) => (
          <option key={option} value={option} className="bg-slate-950 text-white">
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}
