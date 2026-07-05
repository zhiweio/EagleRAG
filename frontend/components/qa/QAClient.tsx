"use client";

import { AppBar } from "@/components/AppBar";
import {
  getSessionApiSessionsSessionIdGet,
  listMessagesApiSessionsSessionIdMessagesGet,
} from "@/lib/api/generated/sdk.gen";
import { streamQuery, streamSearch } from "@/lib/api/sse";
import { errorMessage } from "@/lib/hooks/useIngest";
import { useFilterStore } from "@/lib/stores/filterStore";
import { type ScopeRef, toQueryScope, useScopeStore } from "@/lib/stores/scopeStore";
import { useUIStore } from "@/lib/stores/uiStore";
import type {
  Message,
  MessageListResponse,
  QuerySources,
  RouteInfo,
  Session,
  Step,
} from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";
import { ChatPanel } from "./ChatPanel";
import { HistoryDrawer } from "./HistoryDrawer";
import { ImageLightbox } from "./ImageLightbox";
import { QAToast, type QAToastItem } from "./QAToast";
import { SourcesPanel } from "./SourcesPanel";
import { findImageSourceIndex } from "./sources-utils";
import type { AskMode, ChatMessage, Mode, PreviewTarget } from "./types";

/** Turn a persisted id list into scope refs (id doubles as label when no label was stored). */
function idsToRefs(ids: string[] | null | undefined): ScopeRef[] {
  return (ids ?? []).map((id) => ({ id, label: id }));
}

function uid(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function hasSources(message: ChatMessage): boolean {
  const s = message.sources;
  return Boolean(s && ((s.text?.length ?? 0) > 0 || (s.image?.length ?? 0) > 0));
}

function toChatMessage(it: Message): ChatMessage {
  const sources = it.sources;
  const normalizedSources = sources && !Array.isArray(sources) ? (sources as QuerySources) : null;
  const steps = Array.isArray(it.steps) ? (it.steps as Step[]) : null;
  return {
    id: it.message_id,
    role: it.role === "user" ? "user" : "assistant",
    content: it.content,
    sources: normalizedSources,
    steps,
    route: null,
    createdAt: it.created_at ?? "",
  };
}

function parseJson<T>(raw: string): T | null {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function QAClient() {
  const t = useTranslations("qa");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("auto");
  const [askMode, setAskMode] = useState<AskMode>("ask");
  const [toasts, setToasts] = useState<QAToastItem[]>([]);
  const [sending, setSending] = useState(false);
  const [focusedMessageId, setFocusedMessageId] = useState<string | null>(null);
  const [focusedSourceIndex, setFocusedSourceIndex] = useState<number | null>(null);
  const [previewIntent, setPreviewIntent] = useState<PreviewTarget | null>(null);
  const [previewIntentKey, setPreviewIntentKey] = useState(0);
  const streamCancelRef = useRef<(() => void) | null>(null);

  const setScope = useScopeStore((s) => s.setScope);
  const clearScope = useScopeStore((s) => s.clear);
  const documentFilter = useFilterStore((s) => s.documentFilter);
  const historyOpen = useUIStore((s) => s.qaHistoryOpen);
  const setHistoryOpen = useUIStore((s) => s.setQaHistoryOpen);
  const setLightboxImageId = useUIStore((s) => s.setQaLightboxImageId);
  const queryClient = useQueryClient();

  const pushToast = useCallback(
    (variant: QAToastItem["variant"], title: string, description?: string) => {
      const id = uid("toast");
      setToasts((prev) => [...prev, { id, variant, title, description }]);
    },
    [],
  );

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  // A citation click focuses that message's sources (and the exact index) in the
  // right-hand panel; new answers reset focus so the panel follows the latest.
  const handleCite = useCallback((messageId: string, index: number) => {
    setFocusedMessageId(messageId);
    setFocusedSourceIndex(index);
  }, []);

  const handlePreviewVisual = useCallback(
    (messageId: string, imageId: string) => {
      const message = messages.find((m) => m.id === messageId);
      const sourceIndex = findImageSourceIndex(message?.sources, imageId);
      setFocusedMessageId(messageId);
      setFocusedSourceIndex(sourceIndex);
      setPreviewIntent({ kind: "image", imageId, title: imageId });
      setPreviewIntentKey((k) => k + 1);
    },
    [messages],
  );

  const clearRailFocus = useCallback(() => {
    setFocusedMessageId(null);
    setFocusedSourceIndex(null);
    setPreviewIntent(null);
    setPreviewIntentKey(0);
  }, []);

  const handleSend = useCallback(
    (query: string, attachmentIds?: string[]) => {
      streamCancelRef.current?.();
      clearRailFocus();
      const now = new Date().toISOString();
      const userMsg: ChatMessage = {
        id: uid("u"),
        role: "user",
        content: query,
        createdAt: now,
      };
      const pendingId = uid("a");
      const isSearch = askMode === "search";
      const pendingMsg: ChatMessage = {
        id: pendingId,
        role: "assistant",
        content: "",
        createdAt: now,
        pending: true,
        streaming: false,
        retrievalOnly: isSearch,
        steps: [],
        sources: { text: [], image: [] },
      };
      setMessages((prev) => [...prev, userMsg, pendingMsg]);
      setSending(true);

      const filters =
        documentFilter.sourceType || documentFilter.pipeline || documentFilter.year != null
          ? {
              source_type: documentFilter.sourceType ?? null,
              pipeline: documentFilter.pipeline ?? null,
              year: documentFilter.year ?? null,
            }
          : null;

      // Read the current scope selection directly (avoids re-creating this
      // callback on every scope edit); union (OR) of kb / documents / tags.
      const { scope_filter: scopeFilter, kb_name } = toQueryScope(useScopeStore.getState());

      const onStreamEvent = (event: { event: string; data: string }) => {
        if (event.event === "session") {
          const data = parseJson<{ session_id?: string }>(event.data);
          if (data?.session_id) setSessionId(data.session_id);
          return;
        }
        if (event.event === "step") {
          const step = parseJson<Step & { name: string }>(event.data);
          if (!step) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingId
                ? {
                    ...m,
                    pending: false,
                    streaming: true,
                    steps: [...(m.steps ?? []), step],
                    route:
                      step.name === "route" ? (step as unknown as RouteInfo) : (m.route ?? null),
                  }
                : m,
            ),
          );
          return;
        }
        if (event.event === "sources") {
          const sources = parseJson<QuerySources>(event.data);
          if (!sources) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingId ? { ...m, pending: false, streaming: true, sources } : m,
            ),
          );
          return;
        }
        if (!isSearch && event.event === "token") {
          const data = parseJson<{ delta?: string }>(event.data);
          const delta = data?.delta ?? "";
          if (!delta) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingId
                ? {
                    ...m,
                    pending: false,
                    streaming: true,
                    content: `${m.content}${delta}`,
                  }
                : m,
            ),
          );
          return;
        }
        if (event.event === "done") {
          const data = parseJson<{
            message_id?: string;
            answer?: string;
            sources?: QuerySources;
            steps?: Step[];
            route?: RouteInfo;
          }>(event.data);
          if (!data) return;
          if (isSearch) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === pendingId
                  ? {
                      ...m,
                      pending: false,
                      streaming: false,
                      retrievalOnly: true,
                      sources: data.sources ?? m.sources ?? { text: [], image: [] },
                      steps: data.steps ?? m.steps ?? [],
                      route: data.route ?? m.route ?? null,
                    }
                  : m,
              ),
            );
          } else {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === pendingId
                  ? {
                      id: data.message_id ?? pendingId,
                      role: "assistant",
                      content: data.answer ?? m.content,
                      sources: data.sources ?? m.sources,
                      steps: data.steps ?? m.steps,
                      route: data.route ?? m.route,
                      createdAt: now,
                      pending: false,
                      streaming: false,
                    }
                  : m,
              ),
            );
          }
          setSending(false);
          streamCancelRef.current = null;
          return;
        }
        if (event.event === "error") {
          const data = parseJson<{ message?: string }>(event.data);
          setMessages((prev) => prev.filter((m) => m.id !== pendingId));
          pushToast("error", t("error.query"), data?.message ?? t("error.query"));
          setSending(false);
          streamCancelRef.current = null;
        }
      };

      const onStreamError = (err: unknown) => {
        setMessages((prev) => prev.filter((m) => m.id !== pendingId));
        pushToast("error", t("error.query"), errorMessage(err));
        setSending(false);
        streamCancelRef.current = null;
      };

      const streamBody = {
        query,
        mode,
        scope: null,
        scope_filter: scopeFilter,
        kb_name,
        filters,
      };

      streamCancelRef.current = isSearch
        ? streamSearch(
            { ...streamBody, attachments: attachmentIds ?? null },
            onStreamEvent,
            onStreamError,
          )
        : streamQuery(
            { ...streamBody, session_id: sessionId, attachments: attachmentIds ?? null },
            onStreamEvent,
            onStreamError,
          );
    },
    [sessionId, mode, askMode, documentFilter, pushToast, t, clearRailFocus],
  );

  const handleSelectSession = useCallback(
    async (id: string) => {
      streamCancelRef.current?.();
      setSending(false);
      try {
        const [session, res] = await Promise.all([
          queryClient.fetchQuery({
            queryKey: ["session", id],
            queryFn: async () => {
              const r = await getSessionApiSessionsSessionIdGet({ path: { session_id: id } });
              if (r.error) throw r.error;
              return r.data as unknown as Session;
            },
          }),
          queryClient.fetchQuery({
            queryKey: ["messages", id, undefined],
            queryFn: async () => {
              const r = await listMessagesApiSessionsSessionIdMessagesGet({
                path: { session_id: id },
              });
              if (r.error) throw r.error;
              return r.data as unknown as MessageListResponse;
            },
          }),
        ]);
        setMessages((res?.items ?? []).map(toChatMessage));
        setSessionId(id);
        const sf = (session?.scope_filter ?? null) as {
          kb_names?: string[];
          document_ids?: string[];
          tags?: string[];
        } | null;
        const kbNames = sf?.kb_names?.length
          ? idsToRefs(sf.kb_names)
          : session?.kb_name && session.kb_name !== "default"
            ? idsToRefs([session.kb_name])
            : [];
        setScope({
          kbNames,
          documents: idsToRefs(sf?.document_ids),
          tags: idsToRefs(sf?.tags),
        });
        clearRailFocus();
      } catch (err: unknown) {
        pushToast("error", t("error.messages"), errorMessage(err));
      }
    },
    [pushToast, t, queryClient, setScope, clearRailFocus],
  );

  const handleNewSession = useCallback(() => {
    streamCancelRef.current?.();
    setSending(false);
    setMessages([]);
    setSessionId(null);
    clearScope();
    clearRailFocus();
  }, [clearScope, clearRailFocus]);

  const handleUploadError = useCallback(
    (reason: "upload" | "invalidImageType" | "imageTooLarge" = "upload") => {
      pushToast("error", t(`error.${reason}`));
    },
    [pushToast, t],
  );

  const handleDeleteSessionError = useCallback(
    (err: unknown) => {
      pushToast("error", t("error.delete"), errorMessage(err));
    },
    [pushToast, t],
  );

  // The panel shows the focused answer's sources, defaulting to the latest
  // assistant message that carries any sources.
  const lastWithSources = [...messages]
    .reverse()
    .find((m) => m.role === "assistant" && hasSources(m));
  const focusedMessage =
    (focusedMessageId ? messages.find((m) => m.id === focusedMessageId && hasSources(m)) : null) ??
    lastWithSources ??
    null;
  const highlightIndex =
    focusedMessage && focusedMessage.id === focusedMessageId ? focusedSourceIndex : null;

  return (
    <div className="flex h-screen flex-col bg-background">
      <AppBar />
      <main className="mx-auto flex w-full min-h-0 max-w-360 flex-1 flex-col gap-6 px-4 py-6 sm:px-8 lg:flex-row">
        <ChatPanel
          messages={messages}
          sending={sending}
          onSend={handleSend}
          mode={mode}
          onModeChange={setMode}
          askMode={askMode}
          onAskModeChange={setAskMode}
          sessionId={sessionId}
          onUploadError={handleUploadError}
          onCite={handleCite}
          onPreviewVisual={handlePreviewVisual}
          onClear={handleNewSession}
          onOpenHistory={() => setHistoryOpen(true)}
        />
        <div className="h-140 w-full shrink-0 lg:h-full lg:w-110">
          <SourcesPanel
            sources={focusedMessage?.sources}
            onImageClick={setLightboxImageId}
            highlightIndex={highlightIndex}
            previewIntent={previewIntent}
            previewIntentKey={previewIntentKey}
          />
        </div>
      </main>

      <HistoryDrawer
        isOpen={historyOpen}
        onOpenChange={setHistoryOpen}
        currentSessionId={sessionId}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onDeleteError={handleDeleteSessionError}
      />

      <ImageLightbox />

      <QAToast toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
