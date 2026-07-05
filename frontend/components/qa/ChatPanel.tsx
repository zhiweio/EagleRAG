"use client";

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Eraser, History } from "lucide-react";
import { useTranslations } from "next-intl";
import { Composer } from "./Composer";
import { MessageBubble } from "./MessageBubble";
import { QAAvatar } from "./QAAvatar";
import type { AskMode, ChatMessage, Mode } from "./types";

interface ChatPanelProps {
  messages: ChatMessage[];
  sending: boolean;
  onSend: (query: string, attachmentIds?: string[]) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  askMode: AskMode;
  onAskModeChange: (mode: AskMode) => void;
  sessionId?: string | null;
  onUploadError: () => void;
  onCite: (messageId: string, index: number) => void;
  onPreviewVisual: (messageId: string, imageId: string) => void;
  onClear: () => void;
  onOpenHistory: () => void;
}

export function ChatPanel({
  messages,
  sending,
  onSend,
  mode,
  onModeChange,
  askMode,
  onAskModeChange,
  sessionId,
  onUploadError,
  onCite,
  onPreviewVisual,
  onClear,
  onOpenHistory,
}: ChatPanelProps) {
  const t = useTranslations("qa");
  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-3xl border border-border bg-surface shadow-[0_2px_8px_0_rgba(0,0,0,0.04)]">
      <div className="flex shrink-0 items-center justify-between gap-2 border-border border-b px-6 py-4">
        <h2 className="flex min-w-0 items-center gap-2.5 truncate font-semibold text-base text-foreground">
          <QAAvatar size="sm" />
          <span className="truncate">{t("assistantTitle")}</span>
        </h2>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onOpenHistory}
            aria-label={t("history.open")}
            className="inline-flex items-center gap-1.5 rounded-xl bg-(--surface-muted) px-3 py-1.5 font-medium text-[13px] text-foreground-secondary transition-colors hover:bg-background-secondary"
          >
            <History size={15} strokeWidth={2} aria-hidden />
            <span className="hidden sm:inline">{t("history.title")}</span>
          </button>
          <button
            type="button"
            onClick={onClear}
            aria-label={t("clear")}
            className="inline-flex items-center gap-1.5 rounded-xl bg-(--surface-muted) px-3 py-1.5 font-medium text-[13px] text-foreground-secondary transition-colors hover:bg-background-secondary"
          >
            <Eraser size={15} strokeWidth={2} aria-hidden />
            <span className="hidden sm:inline">{t("clear")}</span>
          </button>
        </div>
      </div>

      <Conversation className="ai-scope min-h-0 flex-1">
        <ConversationContent className="mx-auto flex w-full max-w-3xl flex-col gap-1 px-6 py-5">
          {isEmpty ? (
            <WelcomeState onPick={(text) => onSend(text)} />
          ) : (
            messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                onCite={onCite}
                onPreviewVisual={onPreviewVisual}
              />
            ))
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="shrink-0">
        <Composer
          onSend={onSend}
          disabled={sending}
          mode={mode}
          onModeChange={onModeChange}
          askMode={askMode}
          onAskModeChange={onAskModeChange}
          sessionId={sessionId}
          onUploadError={onUploadError}
        />
      </div>
    </div>
  );
}

/**
 * WelcomeState — empty chat greeting: AI avatar + intro and two suggestion
 * pills that seed the composer on click.
 */
function WelcomeState({ onPick }: { onPick: (text: string) => void }) {
  const t = useTranslations("qa.empty");
  const pills = [t("pill1"), t("pill2")];
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <QAAvatar size="lg" hero />
      <div className="max-w-xl space-y-1.5">
        <h3 className="font-semibold text-foreground text-lg tracking-tight">{t("title")}</h3>
        <p className="text-foreground-secondary text-sm leading-relaxed">{t("desc")}</p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {pills.map((pill) => (
          <button
            key={pill}
            type="button"
            onClick={() => onPick(pill)}
            className="rounded-full border border-border bg-surface px-3.5 py-2 text-[13px] text-foreground-secondary transition-colors hover:border-accent hover:text-accent"
          >
            {pill}
          </button>
        ))}
      </div>
    </div>
  );
}
