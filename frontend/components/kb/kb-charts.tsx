"use client";

import type { FormatSegment, VolumePoint } from "@/lib/kb/types";
import { ProgressBar } from "@heroui/react";
import { useTranslations } from "next-intl";
import { type ReactNode, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PIPELINE_STYLES, type PipelineKind, fileFormatFromKey } from "./kb-visuals";

/* Shared tooltip style: frosted card (HeroUI overlay tokens). */
const tooltipStyle = {
  background: "var(--overlay)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-xl)",
  fontSize: 12,
  padding: "8px 12px",
  boxShadow: "var(--overlay-shadow)",
} as const;

const FORMAT_PIPELINE: Record<string, PipelineKind | "other"> = {
  pdf_text: "knowhere",
  docx: "knowhere",
  pptx: "knowhere",
  xlsx: "knowhere",
  csv: "knowhere",
  md: "knowhere",
  txt: "knowhere",
  json: "knowhere",
  pdf_scan: "pixelrag",
  web: "pixelrag",
  image: "pixelrag",
  other: "other",
};

const PIPELINE_GROUPS: Array<{ id: PipelineKind | "other"; keys: string[] }> = [
  {
    id: "knowhere",
    keys: ["pdf_text", "docx", "pptx", "xlsx", "csv", "md", "txt", "json"],
  },
  {
    id: "pixelrag",
    keys: ["pdf_scan", "web", "image"],
  },
  { id: "other", keys: ["other"] },
];

function FormatKeyBadge({ formatKey, size = 30 }: { formatKey: string; size?: number }) {
  const f = fileFormatFromKey(formatKey);
  const Icon = f.icon;
  const iconSize = Math.round(size * 0.48);
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-lg"
      style={{ width: size, height: size, backgroundColor: f.soft }}
      aria-hidden
    >
      <Icon style={{ width: iconSize, height: iconSize, color: f.color }} />
    </span>
  );
}

type ChartStatItem = {
  key: string;
  label: string;
  value: ReactNode;
  accent?: boolean;
};

/** Shared 3-column stats row pinned to the bottom of chart cards. */
function ChartStatsFooter({ items }: { items: ChartStatItem[] }) {
  return (
    <dl className="mt-auto grid shrink-0 grid-cols-3 gap-2 border-t border-separator pt-3">
      {items.map((s) => (
        <div
          key={s.key}
          className="flex flex-col gap-1 rounded-xl bg-background-secondary px-3 py-2.5"
        >
          <dt className="text-[11px] text-foreground-tertiary">{s.label}</dt>
          <dd
            className={`font-mono text-base font-semibold leading-none tabular-nums ${
              s.accent ? "text-accent" : "text-foreground"
            }`}
          >
            {s.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Min-height for paired chart cards; grows when the format legend needs more rows. */
export function chartPanelMinHeight(formatTypeCount: number): string {
  if (formatTypeCount >= 8) return "min-h-[28rem]";
  if (formatTypeCount >= 6) return "min-h-[25rem]";
  if (formatTypeCount >= 4) return "min-h-[23rem]";
  return "min-h-[21rem]";
}

/* ============================================================
 * Document Format Distribution
 * HeroUI v3 tokens + ProgressBar legend; pipeline-grouped rows;
 * interactive donut synced with legend hover/focus.
 * ============================================================ */
export function FormatDonut({
  segments,
  centerValue,
  centerLabel,
}: {
  segments: FormatSegment[];
  centerValue: string;
  centerLabel: string;
}) {
  const t = useTranslations("kb.detail");
  const data = useMemo(
    () => segments.map((s, index) => ({ ...s, index, name: s.label })),
    [segments],
  );
  const [active, setActive] = useState<number | null>(null);

  const total = data.reduce((sum, d) => sum + d.value, 0);
  const activeSeg = active == null ? null : (data[active] ?? null);
  const centerTop = activeSeg ? `${activeSeg.value}%` : centerValue;
  const centerBottom = activeSeg ? activeSeg.label : centerLabel;

  const grouped = useMemo(() => {
    const byKey = new Map(data.map((row) => [row.key ?? row.label, row]));
    return PIPELINE_GROUPS.map((group) => ({
      ...group,
      label:
        group.id === "other"
          ? t("format.other")
          : (PIPELINE_STYLES[group.id as PipelineKind]?.label ?? group.id),
      style: group.id === "other" ? null : PIPELINE_STYLES[group.id as PipelineKind],
      items: group.keys.flatMap((key) => {
        const row = byKey.get(key);
        return row ? [row] : [];
      }),
    })).filter((g) => g.items.length > 0);
  }, [data, t]);

  const knowhereShare = data
    .filter((d) => FORMAT_PIPELINE[d.key ?? ""] === "knowhere")
    .reduce((sum, d) => sum + d.value, 0);
  const pixelragShare = data
    .filter((d) => FORMAT_PIPELINE[d.key ?? ""] === "pixelrag")
    .reduce((sum, d) => sum + d.value, 0);

  const stats = [
    { key: "types", label: t("format.types"), value: data.length, accent: false },
    { key: "knowhere", label: t("format.knowhereShare"), value: knowhereShare, accent: false },
    { key: "pixelrag", label: t("format.pixelragShare"), value: pixelragShare, accent: true },
  ] as const;

  const statItems: ChartStatItem[] = stats.map((s) => ({
    key: s.key,
    label: s.label,
    accent: s.accent,
    value: s.key === "types" ? s.value : `${s.value}%`,
  }));

  return (
    <div className="flex h-full flex-col">
      {data.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center px-2">
          <p className="text-center text-xs text-foreground-secondary">{t("format.empty")}</p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-5 lg:flex-row lg:items-start">
          {/* Donut */}
          <div className="mx-auto flex shrink-0 items-center justify-center lg:mx-0">
            <div className="relative h-[160px] w-[160px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={52}
                    outerRadius={74}
                    paddingAngle={2}
                    cornerRadius={5}
                    stroke="var(--surface)"
                    strokeWidth={2}
                    isAnimationActive
                    animationDuration={580}
                    onMouseLeave={() => setActive(null)}
                  >
                    {data.map((entry, i) => (
                      <Cell
                        key={`${entry.key ?? entry.label}-${i}`}
                        fill={entry.color}
                        fillOpacity={active == null || active === i ? 1 : 0.22}
                        onMouseEnter={() => setActive(i)}
                        style={{
                          cursor: "pointer",
                          transition: "fill-opacity 180ms ease",
                        }}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [`${value}%`, String(name)]}
                    contentStyle={tooltipStyle}
                    wrapperStyle={{ outline: "none" }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
                <span className="font-mono text-2xl font-bold leading-none tabular-nums text-foreground">
                  {centerTop}
                </span>
                <span className="mt-1.5 max-w-[6.5rem] truncate text-[10px] font-medium text-foreground-tertiary">
                  {centerBottom}
                </span>
              </div>
            </div>
          </div>

          {/* Pipeline-grouped legend */}
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto lg:pr-0.5">
            {grouped.map((group) => (
              <div key={group.id} className="flex flex-col gap-1.5">
                {group.style ? (
                  <div className="flex items-center gap-2 px-1">
                    <span
                      className="h-1.5 w-1.5 rounded-full"
                      style={{ backgroundColor: group.style.color }}
                      aria-hidden
                    />
                    <span
                      className="text-[11px] font-semibold uppercase tracking-wide"
                      style={{ color: group.style.color }}
                    >
                      {group.label}
                    </span>
                  </div>
                ) : (
                  <span className="px-1 text-[11px] font-semibold uppercase tracking-wide text-foreground-tertiary">
                    {group.label}
                  </span>
                )}
                <ul className="flex flex-col gap-1.5">
                  {group.items.map((entry) => {
                    const on = active === entry.index;
                    return (
                      <li key={entry.key ?? entry.label}>
                        <button
                          type="button"
                          onMouseEnter={() => setActive(entry.index)}
                          onMouseLeave={() => setActive(null)}
                          onFocus={() => setActive(entry.index)}
                          onBlur={() => setActive(null)}
                          className={`flex w-full flex-col gap-2 rounded-xl px-1 py-2 text-left transition-[background-color,box-shadow,opacity] duration-200 ${
                            on
                              ? "bg-accent-soft ring-1 ring-accent/15"
                              : "hover:bg-(--surface-muted)"
                          }`}
                          style={{ opacity: active == null || on ? 1 : 0.48 }}
                          aria-pressed={on}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <span className="flex min-w-0 items-center gap-2.5">
                              <FormatKeyBadge formatKey={entry.key ?? "other"} />
                              <span className="truncate text-[13px] font-medium text-foreground">
                                {entry.label}
                              </span>
                            </span>
                            <span className="shrink-0 font-mono text-[13px] font-semibold tabular-nums text-foreground">
                              {entry.value}%
                            </span>
                          </div>
                          <ProgressBar
                            aria-label={entry.label}
                            value={entry.value}
                            maxValue={100}
                            size="sm"
                            color="default"
                          >
                            <ProgressBar.Track>
                              <ProgressBar.Fill style={{ backgroundColor: entry.color }} />
                            </ProgressBar.Track>
                          </ProgressBar>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
      <ChartStatsFooter items={statItems} />
    </div>
  );
}

type BarLabelProps = {
  x?: number;
  y?: number;
  width?: number;
  value?: number;
  peak: number;
};

function VolumeBarLabel({ x, y, width, value, peak }: BarLabelProps) {
  if (value == null || value <= 0 || x == null || y == null || width == null) return null;
  const isPeak = value === peak && peak > 0;
  return (
    <text
      x={x + width / 2}
      y={y - 8}
      textAnchor="middle"
      fill={isPeak ? "var(--accent)" : "var(--foreground-tertiary)"}
      fontSize={isPeak ? 11 : 10}
      fontWeight={isPeak ? 600 : 500}
      className="font-mono tabular-nums"
    >
      {value}
    </text>
  );
}

/* ============================================================
 * Ingestion Volume · 7d
 * Neutral zero bars; accent-soft tint for data, full accent for peak / hover (HeroUI v3).
 * ============================================================ */
export function VolumeBars({ points }: { points: VolumePoint[] }) {
  const t = useTranslations("kb.detail");
  const data = points.map((p) => ({ day: p.label, value: p.value }));
  const [active, setActive] = useState<number | null>(null);

  const total = data.reduce((sum, d) => sum + d.value, 0);
  const peak = data.reduce((max, d) => Math.max(max, d.value), 0);
  const avg = data.length > 0 ? Math.round((total / data.length) * 10) / 10 : 0;
  const yMax = peak > 0 ? Math.ceil(peak * 1.28) : 8;
  const unit = t("volume.unit");
  const seriesName = t("volume.title").split("·")[0].trim();

  const barFill = (_index: number, value: number) => {
    if (value <= 0) return "var(--surface-muted)";
    return "var(--accent)";
  };

  const barOpacity = (index: number, value: number) => {
    if (value <= 0) return 1;
    const isPeak = value === peak && peak > 0;
    const hovered = active === index;
    const dimmed = active != null && active !== index;
    if (isPeak || hovered) return 1;
    if (dimmed) return 0.2;
    return 0.34;
  };

  const stats = [
    { key: "total", label: t("volume.total7d"), value: total, accent: false },
    { key: "avg", label: t("volume.avg"), value: avg, accent: false },
    { key: "peak", label: t("volume.peak"), value: peak, accent: true },
  ] as const;

  const statItems: ChartStatItem[] = stats.map((s) => ({
    key: s.key,
    label: s.label,
    accent: s.accent,
    value: (
      <>
        {s.value.toLocaleString()}
        <span className="ml-1 text-[11px] font-normal text-foreground-tertiary">{unit}</span>
      </>
    ),
  }));

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1 flex-col">
        {total === 0 ? (
          <p className="mb-3 shrink-0 text-center text-xs text-foreground-secondary">
            {t("volume.empty")}
          </p>
        ) : null}
        <div className="h-[188px] w-full shrink-0">
          <ResponsiveContainer width="100%" height={188}>
            <BarChart
              data={data}
              margin={{ top: 20, right: 2, bottom: 0, left: 2 }}
              onMouseLeave={() => setActive(null)}
            >
              <CartesianGrid
                vertical={false}
                stroke="var(--separator)"
                strokeOpacity={0.75}
                strokeDasharray="4 5"
              />
              <XAxis
                dataKey="day"
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: "var(--foreground-tertiary)" }}
                dy={6}
              />
              <YAxis hide domain={[0, yMax]} />
              <Tooltip
                cursor={{ fill: "var(--accent-soft)", radius: 6 }}
                formatter={(value) => [`${value} ${unit}`, seriesName]}
                contentStyle={tooltipStyle}
                wrapperStyle={{ outline: "none" }}
              />
              <Bar
                dataKey="value"
                radius={[6, 6, 2, 2]}
                maxBarSize={32}
                isAnimationActive
                animationDuration={620}
              >
                {data.map((entry, i) => (
                  <Cell
                    key={entry.day}
                    fill={barFill(i, entry.value)}
                    fillOpacity={barOpacity(i, entry.value)}
                    stroke={active === i ? "var(--accent)" : "transparent"}
                    strokeWidth={active === i ? 1.5 : 0}
                    onMouseEnter={() => setActive(i)}
                    style={{
                      cursor: entry.value > 0 ? "pointer" : "default",
                      transition: "fill 180ms ease, fill-opacity 180ms ease",
                    }}
                  />
                ))}
                <LabelList
                  dataKey="value"
                  content={(props) => (
                    <VolumeBarLabel
                      x={props.x}
                      y={props.y}
                      width={props.width}
                      value={typeof props.value === "number" ? props.value : Number(props.value)}
                      peak={peak}
                    />
                  )}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="min-h-0 flex-1" aria-hidden />
      </div>
      <ChartStatsFooter items={statItems} />
    </div>
  );
}
