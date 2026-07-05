"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface LatencyPoint {
  time: string;
  value: number;
}

interface DashboardLatencyChartProps {
  data: LatencyPoint[];
}

/**
 * DashboardLatencyChart — smooth green area trend for the Service Health card.
 * Uses HeroUI success token for stroke/fill in light theme.
 */
export function DashboardLatencyChart({ data }: DashboardLatencyChartProps) {
  return (
    <ResponsiveContainer width="100%" height={120}>
      <AreaChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -20 }}>
        <defs>
          <linearGradient id="dashboardLatencyFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--success)" stopOpacity={0.28} />
            <stop offset="95%" stopColor="var(--success)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="time"
          tick={{ fontSize: 10, fill: "var(--foreground-tertiary)" }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis hide domain={["dataMin - 5", "dataMax + 5"]} />
        <Tooltip
          contentStyle={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontSize: 11,
          }}
          formatter={(value) => [`${value ?? 0} ms`, ""] as [string, string]}
          labelStyle={{ color: "var(--foreground-secondary)" }}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--success)"
          strokeWidth={2}
          fill="url(#dashboardLatencyFill)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
