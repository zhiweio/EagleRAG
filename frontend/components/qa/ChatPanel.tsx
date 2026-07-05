"use client";

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { History, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { Composer } from "./Composer";
import { MessageBubble } from "./MessageBubble";
import { QAAvatar } from "./QAAvatar";
import type { AskMode, ChatMessage, Mode, UserMessageAttachment } from "./types";

interface ChatPanelProps {
  messages: ChatMessage[];
  sending: boolean;
  onSend: (query: string, attachments?: UserMessageAttachment[]) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  askMode: AskMode;
  onAskModeChange: (mode: AskMode) => void;
  sessionId?: string | null;
  onUploadError: () => void;
  onCite: (messageId: string, index: number) => void;
  onPreviewVisual: (messageId: string, imageId: string) => void;
  onNewChat: () => void;
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
  onNewChat,
  onOpenHistory,
}: ChatPanelProps) {
  const t = useTranslations("qa");
  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-3xl border border-border bg-surface shadow-[0_2px_8px_0_rgba(0,0,0,0.04)]">
      <div className="flex shrink-0 items-center justify-between gap-3 border-border border-b px-5 py-3.5 sm:px-6">
        <h2 className="flex min-w-0 items-center gap-2.5 truncate font-semibold text-base text-foreground">
          <QAAvatar size="sm" />
          <span className="truncate">{t("assistantTitle")}</span>
        </h2>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onNewChat}
            disabled={sending}
            aria-label={t("newChat")}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-xl bg-accent px-2.5 py-1.5 font-semibold text-[13px] text-accent-foreground shadow-[0_2px_6px_0_rgba(4,133,247,0.22)] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50 sm:px-3"
          >
            <Plus size={15} strokeWidth={2.2} aria-hidden />
            <span className="hidden sm:inline">{t("newChat")}</span>
          </button>
          <button
            type="button"
            onClick={onOpenHistory}
            aria-label={t("history.open")}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-xl bg-(--surface-muted) px-2.5 py-1.5 font-medium text-[13px] text-foreground-secondary transition-colors hover:bg-background-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-1 sm:px-3"
          >
            <History size={15} strokeWidth={2} aria-hidden />
            <span className="hidden sm:inline">{t("history.title")}</span>
          </button>
        </div>
      </div>

      <Conversation className="ai-scope min-h-0 flex-1">
        <ConversationContent className="mx-auto flex w-full max-w-3xl flex-col gap-1 px-5 py-5 sm:px-6">
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

      <div className="shrink-0 border-border border-t bg-linear-to-b from-surface to-(--surface-muted)/40">
        <Composer
          onSend={onSend}
          disabled={sending}
          mode={mode}
          onModeChange={onModeChange}
          askMode={askMode}
          onAskModeChange={onAskModeChange}
          sessionId={sessionId}
          onUploadError={onUploadError}
          onNewChat={onNewChat}
          hasMessages={!isEmpty}
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
    <div className="flex min-h-[56vh] flex-col items-center justify-center gap-5 px-2 text-center">
      <QAAvatar size="lg" hero />
      <div className="max-w-md space-y-2">
        <h3 className="font-semibold text-foreground text-lg tracking-tight">{t("title")}</h3>
        <p className="text-foreground-secondary text-sm leading-relaxed">{t("desc")}</p>
      </div>
      <div className="flex flex-wrap justify-center gap-2 pt-1">
        {pills.map((pill) => (
          <button
            key={pill}
            type="button"
            onClick={() => onPick(pill)}
            className="cursor-pointer rounded-full border border-border bg-surface px-3.5 py-2 text-[13px] text-foreground-secondary shadow-[0_1px_2px_0_rgba(0,0,0,0.03)] transition-[border-color,color,box-shadow] hover:border-accent/50 hover:text-accent hover:shadow-[0_2px_8px_0_rgba(4,133,247,0.08)]"
          >
            {pill}
          </button>
        ))}
      </div>
    </div>
  );
}
