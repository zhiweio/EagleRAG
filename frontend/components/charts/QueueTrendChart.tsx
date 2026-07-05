"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface QueueDataPoint {
  name: string;
  length: number;
}

interface QueueTrendChartProps {
  data: QueueDataPoint[];
}

export function QueueTrendChart({ data }: QueueTrendChartProps) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <defs>
          <linearGradient id="queueGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#0485F7" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#0485F7" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
        <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
        <Tooltip
          contentStyle={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            fontSize: 12,
          }}
          formatter={(value) => [value ?? 0, "任务数"] as [string, string]}
        />
        <Area
          type="monotone"
          dataKey="length"
          stroke="#0485F7"
          strokeWidth={2}
          fill="url(#queueGradient)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export type { QueueDataPoint };
