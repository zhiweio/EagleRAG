import type { ComponentType, SVGProps } from "react";

export interface KBStatDef {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** Icon color. */
  color: string;
  /** Badge soft background. */
  soft: string;
  cap: string;
  value: string;
  sub: string;
}

/** 08 · KB management overview stat card (design frame Stat · KB Count / Docs / Nodes / Vectors). */
export function KBStatCard({ def }: { def: KBStatDef }) {
  const Icon = def.icon;
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-[18px] shadow-[0_2px_8px_0_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between">
        <span
          className="inline-flex h-[38px] w-[38px] items-center justify-center rounded-lg"
          style={{ backgroundColor: def.soft }}
        >
          <Icon className="h-[19px] w-[19px]" style={{ color: def.color }} aria-hidden />
        </span>
        <span className="text-xs font-medium text-foreground-tertiary">{def.cap}</span>
      </div>
      <span
        className="font-mono text-3xl font-bold text-foreground"
        style={{ letterSpacing: "-0.5px" }}
      >
        {def.value}
      </span>
      <span className="text-xs text-foreground-tertiary">{def.sub}</span>
    </div>
  );
}
