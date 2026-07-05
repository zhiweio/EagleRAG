"use client";

import { ChevronDown, FileText, Image as ImageIcon, Info, Split } from "lucide-react";
import { useState } from "react";

const TICKS = ["0%", "25%", "50%", "75%", "100%"];

/** 09 · PDF smart-routing probe collapsible panel (slider + routing description + routing pill). */
export function ProbeSlider({
  value,
  onChange,
  title,
  sub,
  sliderLabel,
  explain,
  lowLabel,
  highLabel,
  defaultOpen = true,
}: {
  value: number;
  onChange: (v: number) => void;
  title: string;
  sub: string;
  sliderLabel: string;
  explain: string;
  lowLabel: string;
  highLabel: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      {/* Head */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-[11px] px-3.5 py-[13px] text-left"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-soft">
          <Split className="h-[17px] w-[17px] text-accent-soft-foreground" aria-hidden />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-px">
          <span className="text-[13px] font-semibold text-foreground">{title}</span>
          <span className="font-mono text-[11px] text-foreground-tertiary">{sub}</span>
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-foreground-tertiary transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>

      {/* Body */}
      {open ? (
        <div className="flex flex-col gap-3.5 border-t border-separator bg-(--surface-muted) px-3.5 py-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-foreground">{sliderLabel}</span>
            <span className="rounded-md bg-accent-soft px-[9px] py-[3px] font-mono text-xs font-bold text-accent-soft-foreground">
              {value}%
            </span>
          </div>

          {/* Track */}
          <div className="relative h-1.5 w-full">
            <div className="absolute inset-0 rounded-full bg-default" aria-hidden />
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-accent"
              style={{ width: `${value}%` }}
              aria-hidden
            />
            <span
              className="absolute top-1/2 h-[18px] w-[18px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-accent bg-surface shadow-[0_1px_3px_0_rgba(0,0,0,0.12)]"
              style={{ left: `${value}%` }}
              aria-hidden
            />
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={value}
              onChange={(e) => onChange(Number(e.target.value))}
              aria-label={sliderLabel}
              className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
            />
          </div>

          {/* Ticks */}
          <div className="flex items-center justify-between font-mono text-[10px] text-foreground-tertiary">
            {TICKS.map((t) => (
              <span key={t}>{t}</span>
            ))}
          </div>

          {/* Route explain */}
          <div className="flex gap-2.5 rounded-lg border border-border bg-surface px-3 py-[11px]">
            <Info
              className="mt-0.5 h-[15px] w-[15px] shrink-0 text-foreground-tertiary"
              aria-hidden
            />
            <p className="text-[11.5px] leading-[1.55] text-foreground-secondary">{explain}</p>
          </div>

          {/* Route chips */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-100 px-2.5 py-[5px] text-[11px] font-medium text-purple-700">
              <ImageIcon className="h-[13px] w-[13px] text-purple-600" aria-hidden />
              {lowLabel}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 px-2.5 py-[5px] text-[11px] font-medium text-blue-700">
              <FileText className="h-[13px] w-[13px] text-blue-600" aria-hidden />
              {highLabel}
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
