"use client";

import type { QueuePoint } from "@/lib/health/types";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

/**
 * HealthQueueChart — the smooth two-line queue backlog chart from the Celery
 * dashboard (design frame 04): a blue line for the knowhere (text) queue and a
 * violet line for the pixelrag (GPU) queue.
 */
export function HealthQueueChart({ data }: { data: QueuePoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 12, right: 8, bottom: 4, left: -16 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="4 4" />
        <XAxis
          dataKey="time"
          tick={{ fontSize: 11, fill: "var(--foreground-tertiary)" }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: "var(--foreground-tertiary)" }}
          tickLine={false}
          axisLine={false}
          allowDecimals={false}
          width={32}
        />
        <Line
          type="monotone"
          dataKey="knowhere"
          stroke="#0485F7"
          strokeWidth={2.5}
          dot={{ r: 3, fill: "#0485F7", strokeWidth: 0 }}
          activeDot={{ r: 4 }}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="pixelrag"
          stroke="#7C5CF6"
          strokeWidth={2.5}
          dot={{ r: 3, fill: "#7C5CF6", strokeWidth: 0 }}
          activeDot={{ r: 4 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
