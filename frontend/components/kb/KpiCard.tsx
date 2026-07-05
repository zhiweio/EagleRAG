import type { LucideIcon } from "lucide-react";

export interface KpiDef {
  icon: LucideIcon;
  color: string;
  soft: string;
  value: number;
  caption: string;
}

/** KB Detail top KPI card: icon badge + large value + caption (no emoji). */
export function KpiCard({ icon: Icon, color, soft, value, caption }: KpiDef) {
  return (
    <div className="flex flex-col gap-3.5 rounded-2xl border border-separator bg-surface p-[18px] shadow-[0_2px_8px_0_rgba(0,0,0,0.04)]">
      <span
        className="flex h-[34px] w-[34px] items-center justify-center rounded-lg"
        style={{ backgroundColor: soft }}
      >
        <Icon className="h-[17px] w-[17px]" style={{ color }} aria-hidden />
      </span>
      <span
        className="font-mono text-[30px] font-bold leading-none text-foreground"
        style={{ letterSpacing: "-0.5px" }}
      >
        {value.toLocaleString()}
      </span>
      <span className="text-xs text-foreground-tertiary">{caption}</span>
    </div>
  );
}
