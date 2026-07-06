"use client";

import { cn } from "@/lib/utils";
import { FileText, Image as ImageIcon } from "lucide-react";

export interface SourceFileTab {
  key: string;
  name: string;
  type: "text" | "image";
  firstIndex: number;
}

interface SourceFileTabsProps {
  files: SourceFileTab[];
  activeKey: string | null;
  onSelect: (file: SourceFileTab) => void;
}

/**
 * SourceFileTabs — horizontal file filter within the Sources view.
 * Sits below the rail nav; active file uses a quiet inset pill, not a raised card.
 */
export function SourceFileTabs({ files, activeKey, onSelect }: SourceFileTabsProps) {
  if (files.length <= 1) return null;
  return (
    <div className="scroll-pane-x flex gap-1 pb-0.5" role="tablist" aria-orientation="horizontal">
      {files.map((file) => {
        const active = file.key === activeKey;
        const Icon = file.type === "image" ? ImageIcon : FileText;
        return (
          <button
            key={file.key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onSelect(file)}
            className={cn(
              "inline-flex max-w-44 shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-1",
              active
                ? "bg-accent-soft text-accent-soft-foreground"
                : "text-foreground-secondary hover:bg-(--surface-muted) hover:text-foreground",
            )}
          >
            <Icon size={13} strokeWidth={2} aria-hidden className="shrink-0 opacity-80" />
            <span className="truncate">{file.name}</span>
          </button>
        );
      })}
    </div>
  );
}
