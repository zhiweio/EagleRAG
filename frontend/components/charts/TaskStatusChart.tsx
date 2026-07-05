"use client";

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

interface TaskStatusDataPoint {
  name: string;
  value: number;
}

interface TaskStatusChartProps {
  data: TaskStatusDataPoint[];
}

const STATUS_COLORS: Record<string, string> = {
  pending: "#F5A524",
  running: "#0485F7",
  success: "#17C964",
  failed: "#FF383C",
};

export function TaskStatusChart({ data }: TaskStatusChartProps) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={80}
          paddingAngle={2}
        >
          {data.map((entry) => (
            <Cell key={entry.name} fill={STATUS_COLORS[entry.name] ?? "#888"} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

export type { TaskStatusDataPoint };
