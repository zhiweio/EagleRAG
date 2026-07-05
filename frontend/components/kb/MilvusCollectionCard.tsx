/** Milvus Collection storage-level card, matching design frame 10 Storage Section. */
import { Database } from "lucide-react";

export function MilvusCollectionCard({
  name,
  desc,
  entities,
  model,
  index,
  capacityPct,
  chipBg,
  chipFg,
  fillColor,
  modelLabel,
  indexLabel,
  entitiesCap,
  capacityLabel,
}: {
  name: string;
  desc: string;
  entities: number;
  model: string;
  index: string;
  capacityPct: number;
  chipBg: string;
  chipFg: string;
  fillColor: string;
  modelLabel: string;
  indexLabel: string;
  entitiesCap: string;
  capacityLabel: string;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(capacityPct)));
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-separator bg-surface p-5 shadow-[0_2px_8px_0_rgba(0,0,0,0.04)]">
      {/* Top: badge + chip + desc */}
      <div className="flex items-center gap-3">
        <span
          className="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-lg"
          style={{ backgroundColor: chipBg }}
        >
          <Database className="h-[19px] w-[19px]" style={{ color: chipFg }} aria-hidden />
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="rounded-full px-2.5 py-1 font-mono text-xs font-semibold"
            style={{ backgroundColor: chipBg, color: chipFg }}
          >
            {name}
          </span>
          <span className="text-[13px] font-medium text-foreground-secondary">{desc}</span>
        </div>
      </div>

      {/* Metric + Spec */}
      <div className="flex items-end gap-6">
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[28px] font-bold leading-none text-foreground">
            {entities.toLocaleString()}
          </span>
          <span className="text-xs text-foreground-tertiary">{entitiesCap}</span>
        </div>
        <div className="flex flex-1 flex-col gap-1.5">
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-foreground-tertiary">{modelLabel}</span>
            <span className="font-medium text-foreground-secondary">{model}</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-foreground-tertiary">{indexLabel}</span>
            <span className="font-medium text-foreground-secondary">{index}</span>
          </div>
        </div>
      </div>

      {/* Capacity */}
      <div className="flex flex-col gap-1.5">
        <div className="h-2 w-full overflow-hidden rounded-full bg-(--surface-muted)">
          <div
            className="h-full rounded-full"
            style={{ width: `${pct}%`, backgroundColor: fillColor }}
          />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold" style={{ color: fillColor }}>
            {capacityLabel}
          </span>
        </div>
      </div>
    </div>
  );
}
