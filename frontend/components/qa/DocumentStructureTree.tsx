"use client";

import { Loader } from "@/components/ai-elements/loader";
import { imageUrl } from "@/lib/api/client";
import { useDocumentStructure } from "@/lib/hooks/useDocuments";
import type { DocumentStructureNode } from "@/lib/types";
import { ChevronRight, FileBox, FileText, Hash, ImageIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useLayoutEffect, useMemo, useRef } from "react";
import { MarkdownSnippet } from "./MarkdownSnippet";
import type { PreviewTarget } from "./types";

interface DocumentStructureTreeProps {
  documentId: string | null;
  /** Section paths to highlight (retrieved text chunks + visual parent sections). */
  highlightPaths: Set<string>;
  /** Path to auto-scroll into view when it changes. */
  focusPath: string | null;
  onImageClick: (imageId: string) => void;
  onPreview: (target: PreviewTarget) => void;
}

/** A path is "on the retrieved branch" if it is, or is an ancestor of, a hit. */
function isHighlighted(path: string, hits: Set<string>): boolean {
  if (hits.has(path)) return true;
  for (const hit of hits) {
    if (hit.startsWith(`${path}/`)) return true;
  }
  return false;
}

export function DocumentStructureTree({
  documentId,
  highlightPaths,
  focusPath,
  onImageClick,
  onPreview,
}: DocumentStructureTreeProps) {
  const t = useTranslations("qa.structure");
  const { data, isLoading, isError } = useDocumentStructure(documentId);
  const nodeRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const registerNode = (path: string, el: HTMLDivElement | null) => {
    if (el) nodeRefs.current.set(path, el);
    else nodeRefs.current.delete(path);
  };

  const visualsBySection = useMemo(() => {
    const map = new Map<string, NonNullable<typeof data>["visuals"]>();
    for (const v of data?.visuals ?? []) {
      const key = v.parent_section ?? "";
      const list = map.get(key) ?? [];
      list.push(v);
      map.set(key, list);
    }
    return map;
  }, [data]);

  if (!documentId) {
    return <EmptyHint text={t("pickHint")} />;
  }
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-foreground-secondary text-sm">
        <Loader size={15} /> {t("loading")}
      </div>
    );
  }
  if (isError || !data) {
    return <EmptyHint text={t("error")} />;
  }

  const sections = data.sections ?? [];
  const rootVisuals = visualsBySection.get("") ?? [];

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border bg-(--surface-muted) p-3">
        <div className="flex items-center gap-2">
          <FileBox size={15} strokeWidth={2} className="shrink-0 text-accent" aria-hidden />
          <span
            className="min-w-0 flex-1 truncate font-medium text-[13px] text-foreground"
            title={data.name ?? documentId}
          >
            {data.name ?? documentId}
          </span>
          {data.has_source_file ? (
            <button
              type="button"
              onClick={() =>
                onPreview({
                  kind: "file",
                  documentId: data.document_id,
                  title: data.name ?? undefined,
                  sourceType: data.source_type ?? null,
                })
              }
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 font-medium text-[11px] text-foreground-secondary transition-colors hover:bg-background-secondary"
            >
              <FileText size={12} strokeWidth={2} aria-hidden />
              {t("openFile")}
            </button>
          ) : null}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5 font-mono text-[10.5px] text-foreground-tertiary">
          {data.kb_name ? <Meta label="kb" value={data.kb_name} /> : null}
          {data.pipeline ? <Meta label="pipeline" value={data.pipeline} /> : null}
          {data.source ? <Meta label="tree" value={data.source} /> : null}
          {typeof data.visual_count === "number" ? (
            <Meta label="visuals" value={String(data.visual_count)} />
          ) : null}
        </div>
      </div>

      {sections.length === 0 && rootVisuals.length === 0 ? (
        <EmptyHint text={t("empty")} />
      ) : (
        <div className="space-y-0.5">
          {sections.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              hits={highlightPaths}
              focusPath={focusPath}
              registerNode={registerNode}
              visualsBySection={visualsBySection}
              onImageClick={onImageClick}
            />
          ))}
          {rootVisuals.length > 0 ? (
            <VisualStrip visuals={rootVisuals} onImageClick={onImageClick} label={t("visuals")} />
          ) : null}
        </div>
      )}
    </div>
  );
}

function TreeNode({
  node,
  depth,
  hits,
  focusPath,
  registerNode,
  visualsBySection,
  onImageClick,
}: {
  node: DocumentStructureNode;
  depth: number;
  hits: Set<string>;
  focusPath: string | null;
  registerNode: (path: string, el: HTMLDivElement | null) => void;
  visualsBySection: Map<
    string,
    NonNullable<ReturnType<typeof useDocumentStructure>["data"]>["visuals"]
  >;
  onImageClick: (imageId: string) => void;
}) {
  const t = useTranslations("qa.structure");
  const highlighted = isHighlighted(node.path, hits);
  const isFocus = focusPath === node.path;
  const children = node.children ?? [];
  const visuals = visualsBySection.get(node.path) ?? [];
  const rowRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    if (!isFocus) return;
    rowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [isFocus]);

  return (
    <div>
      <div
        ref={(el) => {
          rowRef.current = el;
          registerNode(node.path, el);
        }}
        style={{ paddingLeft: `${depth * 14}px` }}
        className={`group flex items-start gap-1.5 rounded-lg px-2 py-1.5 transition-colors ${
          highlighted ? "bg-accent-soft" : "hover:bg-(--surface-muted)"
        } ${isFocus ? "ring-2 ring-accent" : ""}`}
      >
        <ChevronRight
          size={13}
          strokeWidth={2}
          className={`mt-0.5 shrink-0 ${children.length > 0 ? "text-foreground-tertiary" : "opacity-0"}`}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`min-w-0 flex-1 truncate text-[12.5px] ${
                highlighted ? "font-semibold text-accent" : "font-medium text-foreground"
              }`}
              title={node.title ?? node.path}
            >
              {node.title || node.path.split("/").pop() || node.path}
            </span>
            {typeof node.chunk_count === "number" && node.chunk_count > 0 ? (
              <span className="inline-flex shrink-0 items-center gap-0.5 font-mono text-[10px] text-foreground-tertiary">
                <Hash size={9} strokeWidth={2.5} aria-hidden />
                {node.chunk_count}
              </span>
            ) : null}
          </div>
          {node.summary ? (
            <MarkdownSnippet
              lineClamp={2}
              className="mt-0.5 text-[11.5px] text-foreground-tertiary"
            >
              {node.summary}
            </MarkdownSnippet>
          ) : null}
        </div>
      </div>

      {visuals.length > 0 ? (
        <div style={{ paddingLeft: `${(depth + 1) * 14}px` }}>
          <VisualStrip visuals={visuals} onImageClick={onImageClick} label={t("visuals")} />
        </div>
      ) : null}

      {children.map((child) => (
        <TreeNode
          key={child.path}
          node={child}
          depth={depth + 1}
          hits={hits}
          focusPath={focusPath}
          registerNode={registerNode}
          visualsBySection={visualsBySection}
          onImageClick={onImageClick}
        />
      ))}
    </div>
  );
}

function VisualStrip({
  visuals,
  onImageClick,
  label,
}: {
  visuals: NonNullable<ReturnType<typeof useDocumentStructure>["data"]>["visuals"];
  onImageClick: (imageId: string) => void;
  label: string;
}) {
  const items = (visuals ?? []).filter((v) => v.image_id);
  if (items.length === 0) return null;
  return (
    <div className="my-1 flex flex-wrap items-center gap-1.5 px-2">
      <span className="inline-flex items-center gap-1 text-[10.5px] text-foreground-tertiary">
        <ImageIcon size={11} strokeWidth={2} aria-hidden />
        {label}
      </span>
      {items.map((v) => (
        <button
          key={v.image_id}
          type="button"
          onClick={() => v.image_id && onImageClick(v.image_id)}
          className="h-11 w-11 shrink-0 overflow-hidden rounded-md border border-border transition-transform hover:scale-105"
          title={v.content_summary ?? v.image_id ?? ""}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl(v.image_id as string)}
            alt={v.image_id ?? ""}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        </button>
      ))}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded bg-surface px-1.5 py-0.5">
      <span className="text-foreground-tertiary">{label}</span>
      <span className="text-foreground-secondary">{value}</span>
    </span>
  );
}

function EmptyHint({ text }: { text: string }) {
  return <p className="px-1 py-6 text-center text-foreground-tertiary text-xs">{text}</p>;
}
