"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatCurrency } from "@/lib/format";
import type { ChartDatum } from "@/lib/types";

interface CostChartProps {
  title: string;
  data: ChartDatum[];
}

export function CostChart({ title, data }: CostChartProps) {
  return (
    <section className="rounded-3xl border border-white/10 bg-white/[0.03] p-6">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">Costs</p>
      <h2 className="mt-2 text-2xl font-semibold text-white">{title}</h2>

      <div className="mt-6 h-80">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid stroke="rgba(148, 163, 184, 0.12)" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value: number) => `$${value.toFixed(2)}`}
            />
            <Tooltip
              cursor={{ fill: "rgba(255,255,255,0.04)" }}
              contentStyle={{
                backgroundColor: "#020617",
                borderColor: "rgba(255,255,255,0.08)",
                borderRadius: "16px",
              }}
              formatter={(value) =>
                formatCurrency(typeof value === "number" ? value : Number(value || 0))
              }
            />
            <Bar dataKey="value" fill="#f97316" radius={[10, 10, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
