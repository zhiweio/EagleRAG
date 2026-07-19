"use client";

import type { RoutingMode } from "@/components/ingest/RoutingModeCards";
import {
  type UrlIngestError,
  type UrlValidateResponse,
  errorMessage,
  parseUrlValidateError,
  useIngestUrl,
  validateIngestUrl,
} from "@/lib/hooks/useIngest";
import type { IngestResponse } from "@/lib/types";
import { Button } from "@heroui/react";
import { AlertCircle, CheckCircle2, Globe, Link2, Loader2, ScanSearch } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

interface UrlInputZoneProps {
  onIngested: (response: IngestResponse, name: string) => void;
  onError: (name: string, message: string) => void;
  onQueued?: () => void;
  kbName: string;
  mode: RoutingMode;
}

/** Known backend URL / limit error codes that have a localized message key. */
const KNOWN_URL_ERROR_CODES = [
  "invalid_url_format",
  "url_target_forbidden",
  "url_unreachable",
  "url_timeout",
  "url_bad_status",
  "url_ssl_error",
  "file_too_large",
  "pdf_too_many_pages",
  "pdf_unreadable",
] as const;

const URL_FORMAT_REGEX = /^https?:\/\/.+/;
const VALIDATE_DEBOUNCE_MS = 400;
/** Safety net only — server HTML preflight is typically &lt; 5s. */
const VALIDATE_CLIENT_TIMEOUT_MS = 20_000;

type PreviewState = "idle" | "validating" | "ok" | "error";

function routingFilename(url: string, mode: RoutingMode): string | undefined {
  if (mode === "auto") return undefined;
  const prefix = mode === "knowhere" ? "knowhere:" : "pixelrag:";
  return `${prefix}${url}`;
}

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "AbortError") return true;
  if (err instanceof Error && err.name === "AbortError") return true;
  return false;
}

/**
 * UrlInputZone — URL tab: debounced server validate, then fast enqueue.
 * Sibling to UploadZone; KB selection and routing live in IngestClient.
 */
export function UrlInputZone({ onIngested, onError, onQueued, kbName, mode }: UrlInputZoneProps) {
  const t = useTranslations("ingest");
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [previewState, setPreviewState] = useState<PreviewState>("idle");
  const [preview, setPreview] = useState<UrlValidateResponse | null>(null);
  const [submitError, setSubmitError] = useState<UrlIngestError | null>(null);
  const ingestUrl = useIngestUrl();
  const requestIdRef = useRef(0);
  const validatedUrlRef = useRef("");
  const tRef = useRef(t);
  tRef.current = t;

  const trimmed = url.trim();
  const formatInvalid = trimmed.length > 0 && !URL_FORMAT_REGEX.test(trimmed);
  const looksLikePdf = trimmed.toLowerCase().includes(".pdf");
  const previewOk =
    previewState === "ok" && preview !== null && validatedUrlRef.current === trimmed;
  const canSubmit =
    trimmed.length > 0 && !formatInvalid && Boolean(kbName) && previewOk && !submitting;

  useEffect(() => {
    if (!trimmed || formatInvalid) {
      setPreviewState("idle");
      setPreview(null);
      setSubmitError(null);
      validatedUrlRef.current = "";
      return;
    }

    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    setPreviewState("validating");
    setPreview(null);
    setSubmitError(null);
    validatedUrlRef.current = "";

    let timeoutId: number | undefined;
    const debounceId = window.setTimeout(() => {
      timeoutId = window.setTimeout(() => {
        controller.abort("timeout");
      }, VALIDATE_CLIENT_TIMEOUT_MS);

      void validateIngestUrl(trimmed, controller.signal)
        .then((resp) => {
          if (requestId !== requestIdRef.current) return;
          validatedUrlRef.current = trimmed;
          setPreview(resp);
          setPreviewState("ok");
          setSubmitError(null);
        })
        .catch((err: unknown) => {
          if (requestId !== requestIdRef.current) return;
          if (controller.signal.reason === "timeout") {
            setSubmitError({
              code: "url_timeout",
              reason: tRef.current("url.error.url_timeout"),
            });
            setPreviewState("error");
            return;
          }
          if (controller.signal.aborted || isAbortError(err)) return;
          const structured = parseUrlValidateError(err);
          if (structured) {
            setSubmitError(structured);
          } else {
            setSubmitError({ code: "fallback", reason: errorMessage(err) });
          }
          setPreviewState("error");
        })
        .finally(() => {
          if (timeoutId !== undefined) window.clearTimeout(timeoutId);
        });
    }, VALIDATE_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(debounceId);
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      controller.abort("cleanup");
    };
  }, [trimmed, formatInvalid]);

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const resp = await ingestUrl.mutateAsync({
        url: trimmed,
        filename: routingFilename(trimmed, mode),
        kb_name: kbName || undefined,
      });
      onIngested(resp, trimmed);
      onQueued?.();
      setUrl("");
      setPreview(null);
      setPreviewState("idle");
      validatedUrlRef.current = "";
    } catch (err) {
      const structured = parseUrlValidateError(err);
      if (structured) {
        setSubmitError(structured);
        onError(trimmed, structured.reason);
      } else {
        const message = errorMessage(err);
        setSubmitError({ code: "fallback", reason: message });
        onError(trimmed, message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  function resolveErrorMessage(code: string): string {
    if (code === "file_too_large") {
      return t("upload.error.file_too_large", { maxMb: 200 });
    }
    if (code === "pdf_too_many_pages") {
      return t("upload.error.pdf_too_many_pages", {
        pages: preview?.page_count ?? "?",
        max: 200,
      });
    }
    if (code === "pdf_unreadable") {
      return t("upload.error.pdf_unreadable");
    }
    const known = (KNOWN_URL_ERROR_CODES as readonly string[]).includes(code);
    if (known && (code.startsWith("url_") || code === "invalid_url_format")) {
      return t(`url.error.${code}`);
    }
    return t("url.error.fallback");
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-semibold text-foreground">{t("url.title")}</h2>
          <span className="inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-semibold text-success">
            <ScanSearch className="h-3 w-3" aria-hidden />
            {t("upload.autoDetect")}
          </span>
        </div>
      </div>

      <div className="relative">
        <span className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-foreground-tertiary">
          <Globe className="h-4 w-4" aria-hidden />
        </span>
        <input
          type="url"
          inputMode="url"
          autoComplete="url"
          spellCheck={false}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canSubmit) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
          placeholder={t("url.placeholder")}
          className="h-11 w-full rounded-xl border border-border bg-surface pr-3.5 pl-10 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-tertiary focus:border-accent"
        />
        <span className="pointer-events-none absolute top-1/2 right-3.5 -translate-y-1/2 text-foreground-tertiary">
          <Link2 className="h-4 w-4" aria-hidden />
        </span>
      </div>

      {formatInvalid ? (
        <p className="flex items-center gap-1.5 text-xs text-danger">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden />
          {t("url.invalidFormat")}
        </p>
      ) : previewState === "validating" ? (
        <p className="flex items-center gap-1.5 text-xs text-foreground-secondary">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          {looksLikePdf ? t("url.checkingPdf") : t("url.checking")}
        </p>
      ) : previewOk && preview ? (
        <div className="flex items-start gap-2 rounded-lg border border-success/30 bg-success-soft/40 px-3 py-2">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
          <div className="min-w-0 text-xs text-foreground-secondary">
            <p className="font-medium text-foreground">
              {preview.resource_kind === "pdf"
                ? t("url.preview.pdf", {
                    pages: preview.page_count ?? "—",
                    status: preview.status_code,
                  })
                : preview.resource_kind === "image"
                  ? t("url.preview.image", { status: preview.status_code })
                  : t("url.preview.ok", { status: preview.status_code })}
            </p>
            {preview.final_url && preview.final_url !== trimmed ? (
              <p className="mt-0.5 truncate text-[11px] text-foreground-tertiary">
                {preview.final_url}
              </p>
            ) : null}
            {preview.ssl_insecure ? (
              <p className="mt-0.5 text-[11px] text-foreground-tertiary">
                {t("url.preview.sslInsecure")}
              </p>
            ) : null}
          </div>
        </div>
      ) : submitError ? (
        <div className="flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft p-3">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-danger">
              {resolveErrorMessage(submitError.code)}
            </p>
            {submitError.suggestion ? (
              <p className="mt-0.5 text-[11px] leading-relaxed text-danger/80">
                {submitError.suggestion}
              </p>
            ) : null}
          </div>
        </div>
      ) : !kbName && trimmed && !formatInvalid ? (
        <p className="flex items-center gap-1.5 text-xs text-danger">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden />
          {t("url.kbRequired")}
        </p>
      ) : null}

      <Button
        variant="primary"
        size="lg"
        className="w-full font-semibold shadow-[0_4px_16px_-4px_var(--accent)]"
        isDisabled={!canSubmit}
        onPress={() => void handleSubmit()}
      >
        <Globe className="h-4 w-4" aria-hidden />
        {submitting ? t("url.submitting") : t("url.submit")}
      </Button>
    </div>
  );
}
