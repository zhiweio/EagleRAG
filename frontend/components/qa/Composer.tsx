"use client";

import {
  PromptInput,
  PromptInputBody,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputToolbar,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import {
  MAX_IMAGE_ATTACHMENT_BYTES,
  deleteAttachment,
  uploadAttachment,
} from "@/lib/hooks/useAttachments";
import { type ScopeRef, useScopeStore } from "@/lib/stores/scopeStore";
import type { Document } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button, Popover, Spinner, useOverlayState } from "@heroui/react";
import {
  Check,
  ChevronDown,
  FileText,
  Filter,
  ImageIcon,
  Layers,
  LibraryBig,
  MessagesSquare,
  Route,
  Search,
  Tag,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { MentionAutocomplete } from "./MentionAutocomplete";
import { ScopeFilterDrawer } from "./ScopeFilterDrawer";
import { type AskMode, MODE_OPTIONS, type Mode } from "./types";

const MODE_META: Record<Mode, { icon: LucideIcon; tone: string; iconTone: string }> = {
  auto: {
    icon: Route,
    tone: "bg-accent-soft text-accent",
    iconTone: "bg-accent/10 text-accent",
  },
  text: {
    icon: FileText,
    tone: "bg-slate-100 text-slate-700",
    iconTone: "bg-slate-100 text-slate-600",
  },
  visual: {
    icon: ImageIcon,
    tone: "bg-violet-100 text-violet-700",
    iconTone: "bg-violet-100 text-violet-600",
  },
  hybrid: {
    icon: Layers,
    tone: "bg-teal-50 text-teal-700",
    iconTone: "bg-teal-50 text-teal-600",
  },
};

const IMAGE_ACCEPT =
  "image/png,image/jpeg,image/webp,image/gif,image/bmp,image/tiff,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tiff,.tif";
const ALLOWED_IMAGE_EXTS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".gif",
  ".bmp",
  ".tiff",
  ".tif",
]);
const MAX_IMAGE_MB = MAX_IMAGE_ATTACHMENT_BYTES / (1024 * 1024);

function isAllowedImageFile(file: File): boolean {
  const name = file.name.toLowerCase();
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot) : "";
  if (file.type.startsWith("image/")) {
    return !ext || ALLOWED_IMAGE_EXTS.has(ext);
  }
  return ALLOWED_IMAGE_EXTS.has(ext);
}

interface ComposerProps {
  onSend: (query: string, attachmentIds?: string[]) => void;
  disabled: boolean;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  askMode: AskMode;
  onAskModeChange: (mode: AskMode) => void;
  /** Current session id; associated with uploads so the backend can clean them up. */
  sessionId?: string | null;
  onUploadError: (reason?: "upload" | "invalidImageType" | "imageTooLarge") => void;
}

export function Composer({
  onSend,
  disabled,
  mode,
  onModeChange,
  askMode,
  onAskModeChange,
  sessionId,
  onUploadError,
}: ComposerProps) {
  const t = useTranslations("qa");
  const kbNames = useScopeStore((s) => s.kbNames);
  const documents = useScopeStore((s) => s.documents);
  const tags = useScopeStore((s) => s.tags);
  const mentionKbName = kbNames.length === 1 ? kbNames[0].id : null;
  const addDocument = useScopeStore((s) => s.addDocument);
  const removeItem = useScopeStore((s) => s.removeItem);
  const scopeTotal = kbNames.length + documents.length + tags.length;
  const [value, setValue] = useState("");
  const [uploading, setUploading] = useState(false);
  const [attachmentIds, setAttachmentIds] = useState<string[]>([]);
  const [attachmentNames, setAttachmentNames] = useState<Record<string, string>>({});
  const [attachmentPreviews, setAttachmentPreviews] = useState<Record<string, string>>({});

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const caretRef = useRef(0);
  const prevTokenRef = useRef<string | null>(null);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionIndex, setMentionIndex] = useState(0);
  const [mentionItems, setMentionItems] = useState<Document[]>([]);
  const [dismissed, setDismissed] = useState(false);

  const modeState = useOverlayState();
  const scopeDrawer = useOverlayState();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachmentPreviewsRef = useRef(attachmentPreviews);
  attachmentPreviewsRef.current = attachmentPreviews;

  useEffect(() => {
    return () => {
      for (const url of Object.values(attachmentPreviewsRef.current)) {
        URL.revokeObjectURL(url);
      }
    };
  }, []);

  const handleMentionItems = useCallback((items: Document[]) => {
    setMentionItems(items);
    setMentionIndex((i) => Math.min(i, Math.max(0, items.length - 1)));
  }, []);

  function syncCaret() {
    const el = textareaRef.current;
    if (el) caretRef.current = el.selectionStart ?? value.length;
  }

  function recomputeMention(nextValue: string) {
    const token = getMentionToken(nextValue, caretRef.current);
    if (token === null) {
      setMentionOpen(false);
      prevTokenRef.current = null;
      setDismissed(false);
      return;
    }
    if (prevTokenRef.current === null) {
      setDismissed(false);
      setMentionIndex(0);
    }
    prevTokenRef.current = token;
    setMentionQuery(token);
    if (!dismissed) setMentionOpen(true);
  }

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const next = e.target.value;
    setValue(next);
    syncCaret();
    recomputeMention(next);
  }

  function handleSelect() {
    syncCaret();
    recomputeMention(value);
  }

  function send() {
    const query = value.trim();
    if ((!query && attachmentIds.length === 0) || disabled) return;
    onSend(query, attachmentIds.length > 0 ? attachmentIds : undefined);
    for (const url of Object.values(attachmentPreviews)) {
      URL.revokeObjectURL(url);
    }
    setAttachmentIds([]);
    setAttachmentNames({});
    setAttachmentPreviews({});
    setValue("");
    setMentionOpen(false);
    prevTokenRef.current = null;
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    send();
  }

  function selectMention(docName: string, docId: string) {
    const el = textareaRef.current;
    const caret = el?.selectionStart ?? value.length;
    const before = value.slice(0, caret);
    const after = value.slice(caret);
    const m = before.match(/(?:^|\s)@([^\s@]*)$/);
    if (!m) return;
    const atIdx = caret - m[1].length - 1;
    const insert = `@${docName} `;
    const next = value.slice(0, atIdx) + insert + after;
    setValue(next);
    const nextCaret = atIdx + insert.length;
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(nextCaret, nextCaret);
    });
    addDocument({ id: docId, label: docName });
    setMentionOpen(false);
    prevTokenRef.current = null;
    setDismissed(false);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (mentionOpen && mentionItems.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionIndex((i) => Math.min(i + 1, mentionItems.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const doc = mentionItems[mentionIndex];
        if (doc) selectMention(doc.name, doc.document_id);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setDismissed(true);
        setMentionOpen(false);
        return;
      }
    }
    // Plain Enter falls through to the PromptInput form submit.
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const file = files[0];
    if (!isAllowedImageFile(file)) {
      onUploadError("invalidImageType");
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    if (file.size > MAX_IMAGE_ATTACHMENT_BYTES) {
      onUploadError("imageTooLarge");
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setUploading(true);
    try {
      if (attachmentIds.length > 0) {
        const previous = attachmentIds[0];
        try {
          await deleteAttachment(previous);
        } catch {
          // Best-effort cleanup; local state is replaced regardless.
        }
        const prevPreview = attachmentPreviews[previous];
        if (prevPreview) URL.revokeObjectURL(prevPreview);
      }
      const res = await uploadAttachment(file, sessionId ?? undefined);
      if (!res.attachment_id) return;
      const previewUrl = URL.createObjectURL(file);
      setAttachmentIds([res.attachment_id]);
      setAttachmentNames({ [res.attachment_id]: file.name });
      setAttachmentPreviews({ [res.attachment_id]: previewUrl });
    } catch {
      onUploadError("upload");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function removeAttachment(id: string) {
    const preview = attachmentPreviews[id];
    if (preview) URL.revokeObjectURL(preview);
    void deleteAttachment(id).catch(() => undefined);
    setAttachmentIds((prev) => prev.filter((x) => x !== id));
    setAttachmentNames((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setAttachmentPreviews((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  const canSend = (value.trim().length > 0 || attachmentIds.length > 0) && !disabled;
  const hasChips = scopeTotal > 0 || attachmentIds.length > 0;

  return (
    <div className="border-border border-t bg-surface px-4 py-4 sm:px-6">
      <PromptInput className="bg-(--surface-muted)" onSubmit={handleSubmit}>
        <PromptInputBody>
          {hasChips ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {scopeTotal > 0 ? (
                <>
                  <span className="text-[11px] text-foreground-tertiary">
                    {t("composer.scope")}:
                  </span>
                  {kbNames.map((s) => (
                    <ScopeChip
                      key={`kb-${s.id}`}
                      item={s}
                      icon={LibraryBig}
                      removeLabel={t("composer.scopeClear")}
                      onRemove={() => removeItem("kb", s.id)}
                    />
                  ))}
                  {documents.map((s) => (
                    <ScopeChip
                      key={`doc-${s.id}`}
                      item={s}
                      icon={FileText}
                      removeLabel={t("composer.scopeClear")}
                      onRemove={() => removeItem("document", s.id)}
                    />
                  ))}
                  {tags.map((s) => (
                    <ScopeChip
                      key={`tag-${s.id}`}
                      item={s}
                      icon={Tag}
                      removeLabel={t("composer.scopeClear")}
                      onRemove={() => removeItem("tag", s.id)}
                    />
                  ))}
                </>
              ) : null}
              {attachmentIds.map((id) => (
                <span
                  key={id}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-warning/15 px-2 py-0.5 font-medium text-[11px] text-warning"
                >
                  {attachmentPreviews[id] ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={attachmentPreviews[id]}
                      alt={attachmentNames[id] ?? ""}
                      className="h-6 w-6 rounded object-cover"
                    />
                  ) : (
                    <ImageIcon className="h-3.5 w-3.5" aria-hidden />
                  )}
                  <span className="max-w-32 truncate">{attachmentNames[id] ?? id.slice(0, 8)}</span>
                  <button
                    type="button"
                    aria-label={t("composer.attachRemove")}
                    onClick={() => removeAttachment(id)}
                    className="ml-0.5 inline-flex items-center opacity-70 transition-opacity hover:opacity-100"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          ) : null}

          <div className="relative">
            <MentionAutocomplete
              active={mentionOpen}
              query={mentionQuery}
              activeIndex={mentionIndex}
              kbName={mentionKbName}
              onSelect={(doc) => selectMention(doc.name, doc.document_id)}
              onItemsChange={handleMentionItems}
            />
            <PromptInputTextarea
              ref={textareaRef}
              value={value}
              onChange={handleChange}
              onSelect={handleSelect}
              onKeyDown={handleKeyDown}
              onBlur={() => setMentionOpen(false)}
              placeholder={t("composer.placeholder")}
              aria-label={t("composer.placeholder")}
            />
          </div>
        </PromptInputBody>

        <PromptInputToolbar>
          <PromptInputTools>
            <AskSearchToggle mode={askMode} onChange={onAskModeChange} />

            <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />

            <ImageUploadButton
              disabled={disabled}
              uploading={uploading}
              onClick={() => fileInputRef.current?.click()}
            />

            <ModePicker
              mode={mode}
              isOpen={modeState.isOpen}
              onOpenChange={modeState.setOpen}
              onSelect={(m) => {
                onModeChange(m);
                modeState.close();
              }}
            />

            <Button
              variant="ghost"
              size="sm"
              aria-label={t("scopeDrawer.open")}
              onPress={() => scopeDrawer.setOpen(true)}
              className="h-8 shrink-0 gap-1.5 rounded-full px-2.5 text-foreground-secondary"
            >
              <Filter className="h-4 w-4" />
              <span className="max-w-32 truncate text-xs">
                {scopeTotal > 0
                  ? t("scopeDrawer.selected", { count: scopeTotal })
                  : t("scopeDrawer.all")}
              </span>
            </Button>
          </PromptInputTools>

          <PromptInputSubmit
            status={disabled ? "submitted" : "ready"}
            disabled={!canSend}
            aria-label={t("composer.send")}
          />
        </PromptInputToolbar>
      </PromptInput>

      <input
        ref={fileInputRef}
        type="file"
        accept={IMAGE_ACCEPT}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      <ScopeFilterDrawer isOpen={scopeDrawer.isOpen} onOpenChange={scopeDrawer.setOpen} />
    </div>
  );
}

/** Image upload trigger with hover/focus tooltip describing format and size limits. */
function ImageUploadButton({
  disabled,
  uploading,
  onClick,
}: {
  disabled: boolean;
  uploading: boolean;
  onClick: () => void;
}) {
  const t = useTranslations("qa");
  const hintId = "composer-image-upload-hint";

  return (
    <button
      type="button"
      aria-label={t("composer.attach")}
      aria-describedby={hintId}
      disabled={disabled || uploading}
      onClick={onClick}
      className={cn(
        "group relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
        "text-foreground-secondary transition-colors hover:bg-surface disabled:opacity-50",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2",
      )}
    >
      {uploading ? <Spinner size="sm" /> : <ImageIcon className="h-4 w-4" aria-hidden />}
      <span
        id={hintId}
        role="tooltip"
        className={cn(
          "pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 z-50 w-max max-w-[min(17rem,calc(100vw-2rem))] -translate-x-1/2",
          "rounded-lg border border-border/60 bg-surface px-3 py-2 text-left",
          "shadow-[0_8px_24px_rgba(15,23,42,0.1)]",
          "opacity-0 transition-opacity duration-150",
          "group-hover:opacity-100 group-focus-visible:opacity-100",
        )}
      >
        <span className="block font-medium text-[11px] text-foreground leading-snug">
          {t("composer.attachTooltipTitle")}
        </span>
        <span className="mt-1 block text-[10px] text-foreground-tertiary leading-relaxed">
          {t("composer.attachTooltipFormats")}
        </span>
        <span className="mt-0.5 block text-[10px] text-foreground-tertiary">
          {t("composer.attachTooltipLimits", { maxMb: MAX_IMAGE_MB })}
        </span>
      </span>
    </button>
  );
}

/** Retrieval mode picker — icon-led popover for auto / text / visual / hybrid routing. */
function ModePicker({
  mode,
  isOpen,
  onOpenChange,
  onSelect,
}: {
  mode: Mode;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (mode: Mode) => void;
}) {
  const t = useTranslations("qa");
  const CurrentIcon = MODE_META[mode].icon;

  return (
    <Popover isOpen={isOpen} onOpenChange={onOpenChange}>
      <Popover.Trigger>
        <button
          type="button"
          aria-label={t("composer.mode")}
          aria-expanded={isOpen}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-foreground-secondary transition-colors hover:bg-surface hover:text-foreground"
        >
          <span
            className={`inline-flex h-5 w-5 items-center justify-center rounded-md ${MODE_META[mode].iconTone}`}
          >
            <CurrentIcon className="h-3.5 w-3.5" strokeWidth={2.1} aria-hidden />
          </span>
          <span className="font-medium text-xs">{t(`mode.${mode}`)}</span>
          <ChevronDown
            className={`h-3.5 w-3.5 text-foreground-tertiary transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
            aria-hidden
          />
        </button>
      </Popover.Trigger>
      <Popover.Content className="w-72 p-0" placement="top start">
        <Popover.Dialog aria-label={t("composer.mode")}>
          <div className="flex flex-col">
            <div className="border-border border-b px-3.5 py-2.5">
              <span className="font-semibold text-[11px] text-foreground-secondary uppercase tracking-[0.08em]">
                {t("composer.mode")}
              </span>
            </div>
            <div className="flex flex-col gap-0.5 p-1.5">
              {MODE_OPTIONS.map((m) => {
                const selected = m === mode;
                const meta = MODE_META[m];
                const Icon = meta.icon;
                return (
                  <button
                    key={m}
                    type="button"
                    aria-current={selected ? "true" : undefined}
                    onClick={() => onSelect(m)}
                    className={`flex w-full items-start gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors ${
                      selected
                        ? `${meta.tone} ring-1 ring-current/15`
                        : "hover:bg-(--surface-muted)"
                    }`}
                  >
                    <span
                      className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${meta.iconTone}`}
                    >
                      <Icon className="h-4 w-4" strokeWidth={2} aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span
                        className={`block font-medium text-[13px] leading-tight ${
                          selected ? "" : "text-foreground"
                        }`}
                      >
                        {t(`mode.${m}`)}
                      </span>
                      <span className="mt-0.5 block text-[11px] text-foreground-tertiary leading-snug">
                        {t(`mode.${m}Desc`)}
                      </span>
                    </span>
                    {selected ? (
                      <Check
                        className="mt-1 h-4 w-4 shrink-0 opacity-80"
                        strokeWidth={2.5}
                        aria-hidden
                      />
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}

/** Ask (streamed answer) vs Search (retrieval-only) segmented control. */
function AskSearchToggle({ mode, onChange }: { mode: AskMode; onChange: (m: AskMode) => void }) {
  const t = useTranslations("qa.search");
  const opts: { id: AskMode; label: string; icon: typeof MessagesSquare }[] = [
    { id: "ask", label: t("ask"), icon: MessagesSquare },
    { id: "search", label: t("search"), icon: Search },
  ];
  return (
    <div className="inline-flex shrink-0 items-center rounded-full bg-background-secondary p-0.5">
      {opts.map((opt) => {
        const active = opt.id === mode;
        const Icon = opt.icon;
        return (
          <button
            key={opt.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.id)}
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-medium text-xs transition-colors ${
              active
                ? "bg-surface text-foreground shadow-[0_1px_2px_0_rgba(0,0,0,0.06)]"
                : "text-foreground-tertiary hover:text-foreground-secondary"
            }`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** A removable scope chip (knowledge base / document / tag) shown above the textarea. */
function ScopeChip({
  item,
  icon: Icon,
  removeLabel,
  onRemove,
}: {
  item: ScopeRef;
  icon: typeof LibraryBig;
  removeLabel: string;
  onRemove: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-lg bg-accent-soft px-2 py-0.5 font-medium text-[11px] text-accent">
      <Icon className="h-3 w-3 shrink-0" aria-hidden />
      <span className="max-w-48 truncate">{item.label}</span>
      <button
        type="button"
        aria-label={removeLabel}
        onClick={onRemove}
        className="ml-0.5 inline-flex items-center opacity-70 transition-opacity hover:opacity-100"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

/**
 * Returns the @ mention token at the caret, or null when the caret is not
 * directly inside an `@token` (an `@` at start-of-input or preceded by
 * whitespace, followed by non-space characters up to the caret).
 */
function getMentionToken(value: string, caret: number): string | null {
  const before = value.slice(0, caret);
  const m = before.match(/(?:^|\s)@([^\s@]*)$/);
  return m ? m[1] : null;
}
