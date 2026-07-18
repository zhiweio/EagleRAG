"use client";

import type { RoutingMode } from "@/components/ingest/RoutingModeCards";
import { errorMessage, parseIngestLimitError, useIngestFile } from "@/lib/hooks/useIngest";
import {
  INGEST_MAX_FILE_BYTES,
  INGEST_MAX_PDF_PAGES,
  type IngestLimitViolation,
  checkIngestFileLimits,
} from "@/lib/ingest/limits";
import type { IngestResponse } from "@/lib/types";
import { Button } from "@heroui/react";
import { Snowflake, UploadCloud, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

interface UploadZoneProps {
  onIngested: (response: IngestResponse, name: string) => void;
  onError: (name: string, message: string) => void;
  onBatch: (count: number) => void;
  kbName: string;
  mode: RoutingMode;
}

/** Force routing via filename prefix `knowhere:` / `pixelrag:` (matches backend routing override precedence). */
function applyRoutingPrefix(file: File, mode: RoutingMode): File {
  if (mode === "auto") return file;
  if (file.name.startsWith("knowhere:") || file.name.startsWith("pixelrag:")) return file;
  const prefix = mode === "knowhere" ? "knowhere:" : "pixelrag:";
  return new File([file], `${prefix}${file.name}`, { type: file.type });
}

/**
 * UploadZone — "Upload & Routing Strategy" card body:
 * drag/browse to stage files → submit to the queue. KB selection and routing
 * strategy are rendered by IngestClient (shared with UrlInputZone); the
 * `mode` prop drives the filename routing prefix on submit.
 */
export function UploadZone({ onIngested, onError, onBatch, kbName, mode }: UploadZoneProps) {
  const t = useTranslations("ingest");
  const [staged, setStaged] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const ingestFile = useIngestFile();

  function addFiles(files: File[]) {
    if (files.length === 0) return;
    setStaged((prev) => [...prev, ...files]);
  }

  function removeStaged(index: number) {
    setStaged((prev) => prev.filter((_, i) => i !== index));
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    addFiles(Array.from(event.dataTransfer.files ?? []));
  }

  function handleInputChange(event: React.ChangeEvent<HTMLInputElement>) {
    addFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  }

  function formatLimitMessage(violation: IngestLimitViolation): string {
    if (violation.code === "file_too_large") {
      return t("upload.error.file_too_large", {
        maxMb: Math.round(INGEST_MAX_FILE_BYTES / (1024 * 1024)),
      });
    }
    if (violation.code === "pdf_too_many_pages") {
      return t("upload.error.pdf_too_many_pages", {
        pages: violation.pages ?? 0,
        max: INGEST_MAX_PDF_PAGES,
      });
    }
    return t("upload.error.pdf_unreadable");
  }

  async function handleSubmit() {
    if (staged.length === 0 || busy) return;
    setBusy(true);
    const files = staged;
    let ok = 0;
    await Promise.allSettled(
      files.map(async (file) => {
        try {
          const violation = await checkIngestFileLimits(file);
          if (violation) {
            onError(file.name, formatLimitMessage(violation));
            return;
          }
          const resp = await ingestFile.mutateAsync({
            file: applyRoutingPrefix(file, mode),
            kb_name: kbName || undefined,
          });
          ok += 1;
          onIngested(resp, file.name);
        } catch (err) {
          const limitErr = parseIngestLimitError(err);
          if (limitErr) {
            const suggestion = limitErr.suggestion ? ` ${limitErr.suggestion}` : "";
            onError(file.name, `${limitErr.reason}${suggestion}`);
            return;
          }
          onError(file.name, errorMessage(err));
        }
      }),
    );
    if (ok > 0) onBatch(ok);
    setStaged([]);
    setBusy(false);
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Card header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-semibold text-foreground">{t("upload.title")}</h2>
          <span className="inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-semibold text-success">
            <Snowflake className="h-3 w-3" aria-hidden />
            {t("upload.autoDetect")}
          </span>
        </div>
        <span className="text-[11px] font-medium text-foreground-tertiary">
          {t("upload.step", { current: 1, total: 2 })}
        </span>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-6 py-7 text-center transition-colors ${
          dragging ? "border-accent bg-accent-soft" : "border-border bg-(--surface-muted)"
        }`}
      >
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex h-11 w-11 items-center justify-center rounded-xl bg-surface shadow-[0_1px_3px_0_rgba(0,0,0,0.06)]"
          aria-label={t("upload.dropTitle")}
        >
          <UploadCloud className="h-5 w-5 text-accent" aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="text-sm font-medium text-foreground"
        >
          {t("upload.dropTitle")}
        </button>
        <p className="text-[11px] text-foreground-tertiary">{t("upload.dropHint")}</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleInputChange}
        />
      </div>

      {/* Staged files */}
      {staged.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium text-foreground-tertiary">
            {t("upload.filesSelected", { count: staged.length })}
          </span>
          {staged.map((file, index) => (
            <span
              key={`${file.name}-${index}`}
              className="inline-flex max-w-56 items-center gap-1.5 rounded-full bg-(--surface-muted) px-2.5 py-1 text-[11px] text-foreground"
            >
              <span className="truncate">{file.name}</span>
              <button
                type="button"
                onClick={() => removeStaged(index)}
                aria-label={t("toast.dismiss")}
                className="shrink-0 text-foreground-tertiary hover:text-danger"
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            </span>
          ))}
        </div>
      ) : null}

      {/* Submit */}
      <Button
        variant="primary"
        size="lg"
        className="w-full font-semibold shadow-[0_4px_16px_-4px_var(--accent)]"
        isDisabled={staged.length === 0 || busy}
        onPress={() => void handleSubmit()}
      >
        <Snowflake className="h-4 w-4" aria-hidden />
        {busy ? t("upload.submitting") : t("upload.submit")}
      </Button>
    </div>
  );
}
