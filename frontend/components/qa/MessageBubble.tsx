"use client";

import { Action, Actions } from "@/components/ai-elements/actions";
import { Loader } from "@/components/ai-elements/loader";
import { Message, MessageAvatar, MessageContent } from "@/components/ai-elements/message";
import { Source, Sources, SourcesContent, SourcesTrigger } from "@/components/ai-elements/sources";
import { ThinkingLabel } from "@/components/ai-elements/thinking-indicator";
import { CheckIcon, CopyIcon, FileText, ImageIcon, Search, User } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";
import { AnswerBody } from "./AnswerBody";
import { QAAvatar } from "./QAAvatar";
import { ThinkingTrace } from "./ThinkingTrace";
import {
  flattenSources,
  formatSim,
  sourceCrumbs,
  sourceFileName,
  sourceString,
} from "./sources-utils";
import type { ChatMessage, FlatSource } from "./types";

interface MessageBubbleProps {
  message: ChatMessage;
  /** Focus a cited source (by 1-based flat index) in the evidence rail. */
  onCite: (messageId: string, index: number) => void;
  /** Open a visual slice in the evidence rail preview tab. */
  onPreviewVisual: (messageId: string, imageId: string) => void;
}

export function MessageBubble({ message, onCite, onPreviewVisual }: MessageBubbleProps) {
  const t = useTranslations("qa");
  const isUser = message.role === "user";
  const flat = flattenSources(message.sources);

  const handleCite = useCallback((n: number) => onCite(message.id, n), [onCite, message.id]);
  const handlePreviewVisual = useCallback(
    (imageId: string) => onPreviewVisual(message.id, imageId),
    [message.id, onPreviewVisual],
  );

  if (isUser) {
    return (
      <Message className="items-start" from="user">
        <MessageContent variant="contained">
          <span className="whitespace-pre-wrap wrap-break-word">{message.content}</span>
        </MessageContent>
        <MessageAvatar className="bg-(--bubble) text-foreground-secondary">
          <User size={16} strokeWidth={2} />
        </MessageAvatar>
      </Message>
    );
  }

  return (
    <Message className="items-start" from="assistant">
      <MessageAvatar className="size-8 overflow-hidden bg-transparent p-0">
        <QAAvatar size="sm" />
      </MessageAvatar>
      <MessageContent variant="flat">
        {message.pending ? (
          <ThinkingLabel active className="text-sm">
            {t("loading.thinking")}
          </ThinkingLabel>
        ) : (
          <>
            <ThinkingTrace
              onPreviewVisual={handlePreviewVisual}
              route={message.route}
              steps={message.steps}
              streaming={Boolean(message.streaming)}
            />

            {message.retrievalOnly ? (
              <RetrievalNote count={flat.length} />
            ) : message.content ? (
              <AnswerBody
                content={message.content}
                flat={flat}
                onCite={handleCite}
                streaming={Boolean(message.streaming)}
              />
            ) : message.streaming ? (
              <Loader size={15} />
            ) : (
              <span className="text-foreground-tertiary">—</span>
            )}

            {flat.length > 0 ? <SourceList items={flat} onCite={handleCite} /> : null}

            {!message.streaming && !message.retrievalOnly && message.content ? (
              <MessageToolbar content={message.content} />
            ) : null}
          </>
        )}
      </MessageContent>
    </Message>
  );
}

/** Retrieval-only turn banner (search mode returns sources without an answer). */
function RetrievalNote({ count }: { count: number }) {
  const t = useTranslations("qa");
  return (
    <div className="inline-flex items-center gap-2 rounded-lg bg-secondary px-3 py-1.5 text-foreground-secondary text-xs">
      <Search size={14} strokeWidth={2} className="text-primary" />
      <span>{t("search.retrievalOnly", { count })}</span>
    </div>
  );
}

/** Collapsible provenance list mapping `[n]` to a clickable source row. */
function SourceList({ items, onCite }: { items: FlatSource[]; onCite: (n: number) => void }) {
  const t = useTranslations("qa.sources");
  return (
    <Sources className="mt-1" defaultOpen>
      <SourcesTrigger count={items.length} label={t("count")} />
      <SourcesContent>
        {items.map((item) => {
          const isImage = item.type === "image";
          const name = sourceFileName(item.source) || `#${item.index}`;
          const anchor = isImage
            ? [sourceString(item.source, "page") && `p.${sourceString(item.source, "page")}`]
                .filter(Boolean)
                .join("")
            : sourceCrumbs(item.source).slice(-1)[0] || "";
          const sim = formatSim(item.source);
          return (
            <button
              className="group/src flex w-full items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 text-left transition-colors hover:border-border hover:bg-secondary"
              key={item.index}
              onClick={() => onCite(item.index)}
              type="button"
            >
              <span
                className={`inline-flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full px-1 font-mono text-[10px] ${
                  isImage
                    ? "bg-violet-100 text-violet-700"
                    : "bg-accent-soft text-accent-soft-foreground"
                }`}
              >
                {item.index}
              </span>
              {isImage ? (
                <ImageIcon className="size-3.5 shrink-0 text-violet-500" />
              ) : (
                <FileText className="size-3.5 shrink-0 text-primary" />
              )}
              <span className="min-w-0 flex-1 truncate font-medium text-foreground text-xs">
                {name}
              </span>
              {anchor ? (
                <span className="hidden max-w-40 truncate text-[11px] text-muted-foreground sm:inline">
                  {anchor}
                </span>
              ) : null}
              {sim ? (
                <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">
                  {sim}
                </span>
              ) : null}
            </button>
          );
        })}
      </SourcesContent>
    </Sources>
  );
}

/** Answer-level actions (copy). */
function MessageToolbar({ content }: { content: string }) {
  const t = useTranslations("qa");
  const [copied, setCopied] = useState(false);
  const copy = () => {
    if (typeof navigator === "undefined" || !navigator.clipboard) return;
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <Actions className="mt-0.5">
      <Action label={t("actions.copy")} onClick={copy} tooltip={t("actions.copy")}>
        {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
      </Action>
    </Actions>
  );
}
