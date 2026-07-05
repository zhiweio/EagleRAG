"use client";

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
  ChainOfThoughtStep,
  ChainOfThoughtStepGroup,
  type ChainOfThoughtStepStatus,
  ChainOfThoughtVisualThumb,
} from "@/components/ai-elements/chain-of-thought";
import { imageUrl } from "@/lib/api/client";
import type { RouteInfo, Step } from "@/lib/types";
import {
  AlertTriangle,
  ArrowDownWideNarrow,
  FileText,
  GitFork,
  ImageIcon,
  type LucideIcon,
  Paperclip,
  PenLine,
  Search,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

interface ThinkingTraceProps {
  steps: Step[] | null | undefined;
  route: RouteInfo | null | undefined;
  /** True while the SSE stream is still arriving (illuminates the last step). */
  streaming?: boolean;
  /** Open the matching visual slice in the evidence rail preview tab. */
  onPreviewVisual?: (imageId: string) => void;
}

const RERANK_KEYS = new Set(["text_top", "visual_top", "text_kept", "visual_kept"]);
const RECALL_KEYS = new Set(["text_count", "visual_count"]);

/** Pick an icon + a localized label bucket from a backend step name. */
function stepMeta(name: string | undefined): { icon: LucideIcon; key: string } {
  const lower = (name ?? "").toLowerCase();
  if (lower.includes("route")) return { icon: GitFork, key: "route" };
  if (lower.includes("attach")) return { icon: Paperclip, key: "attach_parse" };
  if (lower.includes("rerank")) return { icon: ArrowDownWideNarrow, key: "rerank" };
  if (lower.includes("recall") || lower.includes("retriev")) return { icon: Search, key: "recall" };
  if (lower.includes("gen")) return { icon: PenLine, key: "generate" };
  if (lower.includes("warn")) return { icon: AlertTriangle, key: "warning" };
  return { icon: Search, key: "recall" };
}

function str(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "";
}

function parseNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.length > 0) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function parseStringArray(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((x) => str(x)).filter(Boolean);
  if (typeof v === "string" && v.startsWith("[")) {
    try {
      const parsed: unknown = JSON.parse(v);
      if (Array.isArray(parsed)) return parsed.map((x) => str(x)).filter(Boolean);
    } catch {
      /* fall through */
    }
  }
  const single = str(v);
  return single ? [single] : [];
}

function pathLeaf(path: string): string {
  const parts = path.split(/[/\\›>]/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

/** Build React keys for lists that may contain duplicate string values. */
function listKeys(values: string[]): string[] {
  const seen = new Map<string, number>();
  return values.map((value) => {
    const count = seen.get(value) ?? 0;
    seen.set(value, count + 1);
    return count === 0 ? value : `${value}::${count}`;
  });
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

function stepExtras(step: Step, bucket: string): [string, unknown][] {
  const skip =
    bucket === "rerank" ? RERANK_KEYS : bucket === "recall" ? RECALL_KEYS : new Set<string>();
  return Object.entries(step).filter(
    ([k, v]) =>
      k !== "name" &&
      k !== "detail" &&
      !skip.has(k) &&
      v !== null &&
      v !== undefined &&
      String(v).length > 0,
  );
}

function RerankStepBody({
  step,
  onPreviewVisual,
}: {
  step: Step;
  onPreviewVisual?: (imageId: string) => void;
}) {
  const t = useTranslations("qa.steps");
  const textTop = parseStringArray(step.text_top);
  const visualTop = parseStringArray(step.visual_top);
  const textKept = parseNumber(step.text_kept) ?? textTop.length;
  const visualKept = parseNumber(step.visual_kept) ?? visualTop.length;
  const textKeys = listKeys(textTop);
  const visualKeys = listKeys(visualTop);

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-2 py-0.5 font-medium text-[10.5px] text-accent-soft-foreground">
          <FileText aria-hidden className="size-3 shrink-0" />
          {t("rerankTextKept", { count: textKept })}
        </span>
        <span className="inline-flex items-center gap-1 rounded-md bg-violet-100 px-2 py-0.5 font-medium text-[10.5px] text-violet-700">
          <ImageIcon aria-hidden className="size-3 shrink-0" />
          {t("rerankVisualKept", { count: visualKept })}
        </span>
      </div>

      {textTop.length > 0 ? (
        <ChainOfThoughtStepGroup label={t("textTop")}>
          <ChainOfThoughtSearchResults>
            {textTop.map((path, i) => (
              <ChainOfThoughtSearchResult key={textKeys[i]} title={path} tone="text">
                <span className="truncate">{pathLeaf(path)}</span>
              </ChainOfThoughtSearchResult>
            ))}
          </ChainOfThoughtSearchResults>
        </ChainOfThoughtStepGroup>
      ) : null}

      {visualTop.length > 0 ? (
        <ChainOfThoughtStepGroup label={t("visualTop")}>
          <div className="flex gap-2 overflow-x-auto p-0.5">
            {visualTop.map((id, i) => (
              <ChainOfThoughtVisualThumb
                alt={id}
                aria-label={t("previewVisual", { rank: i + 1 })}
                key={visualKeys[i]}
                onClick={onPreviewVisual ? () => onPreviewVisual(id) : undefined}
                rank={i + 1}
                src={imageUrl(id)}
              />
            ))}
          </div>
        </ChainOfThoughtStepGroup>
      ) : null}
    </div>
  );
}

function RecallStepBody({ step }: { step: Step }) {
  const t = useTranslations("qa.steps");
  const textCount = parseNumber(step.text_count);
  const visualCount = parseNumber(step.visual_count);
  if (textCount == null && visualCount == null) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {textCount != null ? (
        <span className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-2 py-0.5 font-medium text-[10.5px] text-accent-soft-foreground">
          <FileText aria-hidden className="size-3 shrink-0" />
          {t("recallText", { count: textCount })}
        </span>
      ) : null}
      {visualCount != null ? (
        <span className="inline-flex items-center gap-1 rounded-md bg-violet-100 px-2 py-0.5 font-medium text-[10.5px] text-violet-700">
          <ImageIcon aria-hidden className="size-3 shrink-0" />
          {t("recallVisual", { count: visualCount })}
        </span>
      ) : null}
    </div>
  );
}

function GenericStepExtras({ step, bucket }: { step: Step; bucket: string }) {
  const extras = stepExtras(step, bucket);
  if (extras.length === 0) return null;
  return (
    <ChainOfThoughtSearchResults>
      {extras.map(([k, v]) => (
        <ChainOfThoughtSearchResult key={k} title={`${k}: ${formatValue(v)}`}>
          <span className="text-muted-foreground">{k}</span>
          <span className="font-semibold">{formatValue(v)}</span>
        </ChainOfThoughtSearchResult>
      ))}
    </ChainOfThoughtSearchResults>
  );
}

function StepBody({
  step,
  bucket,
  onPreviewVisual,
}: {
  step: Step;
  bucket: string;
  onPreviewVisual?: (imageId: string) => void;
}) {
  if (bucket === "rerank") {
    return (
      <>
        <RerankStepBody onPreviewVisual={onPreviewVisual} step={step} />
        <GenericStepExtras bucket={bucket} step={step} />
      </>
    );
  }
  if (bucket === "recall") {
    return (
      <>
        <RecallStepBody step={step} />
        <GenericStepExtras bucket={bucket} step={step} />
      </>
    );
  }
  return <GenericStepExtras bucket={bucket} step={step} />;
}

function hasStepBody(step: Step, bucket: string): boolean {
  if (bucket === "rerank") {
    return (
      parseStringArray(step.text_top).length > 0 ||
      parseStringArray(step.visual_top).length > 0 ||
      parseNumber(step.text_kept) != null ||
      parseNumber(step.visual_kept) != null ||
      stepExtras(step, bucket).length > 0
    );
  }
  if (bucket === "recall") {
    return (
      parseNumber(step.text_count) != null ||
      parseNumber(step.visual_count) != null ||
      stepExtras(step, bucket).length > 0
    );
  }
  return stepExtras(step, bucket).length > 0;
}

/**
 * ThinkingTrace — the RAG-native "thinking" timeline. The SSE `step` events
 * (route → recall → attach_parse → rerank → generate) plus the routing decision
 * are rendered as an illuminated, collapsible `ChainOfThought`: the last step
 * pulses while the stream is live, provenance readouts (counts, scores, timings)
 * show as mono chips, and the whole trace collapses once the answer arrives.
 */
export function ThinkingTrace({
  steps,
  route,
  streaming = false,
  onPreviewVisual,
}: ThinkingTraceProps) {
  const t = useTranslations("qa.steps");
  const items = steps ?? [];
  const hasRoute = Boolean(route && (route.mode || route.selected || route.reason));

  // Open while streaming; let the user re-toggle afterwards.
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? streaming;

  if (items.length === 0 && !hasRoute) return null;

  const routeMode = str(route?.mode);
  const routeSelected = str(route?.selected);
  const routeReason = str(route?.reason);

  return (
    <ChainOfThought onOpenChange={setUserOpen} open={open}>
      <ChainOfThoughtHeader streaming={streaming}>
        {streaming ? t("thinkingLive") : t("thinkingDone", { count: items.length })}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {hasRoute ? (
          <ChainOfThoughtStep
            description={routeReason || undefined}
            icon={GitFork}
            label={
              <span className="flex items-center gap-1.5">
                {t("route")}
                {routeSelected ? (
                  <span className="font-mono text-[10.5px] text-primary">
                    {routeMode ? `${routeMode} → ` : ""}
                    {routeSelected}
                  </span>
                ) : null}
              </span>
            }
            status="complete"
          />
        ) : null}

        {items.map((step, i) => {
          const { icon, key } = stepMeta(step.name);
          const detail = str(step.detail);
          const isLast = i === items.length - 1;
          const status: ChainOfThoughtStepStatus = streaming && isLast ? "active" : "complete";
          const showBody = hasStepBody(step, key);
          return (
            <ChainOfThoughtStep
              description={detail || undefined}
              icon={icon}
              key={step.name ?? `step-${i}`}
              label={t(key)}
              status={status}
            >
              {showBody ? (
                <StepBody bucket={key} onPreviewVisual={onPreviewVisual} step={step} />
              ) : null}
            </ChainOfThoughtStep>
          );
        })}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}
