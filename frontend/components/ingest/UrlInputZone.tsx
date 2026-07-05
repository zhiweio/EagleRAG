"use client";

import {
  type UrlIngestError,
  errorMessage,
  parseUrlIngestError,
  useIngestUrl,
} from "@/lib/hooks/useIngest";
import type { IngestResponse } from "@/lib/types";
import { Button } from "@heroui/react";
import { AlertCircle, Globe, Link2, Snowflake } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

interface UrlInputZoneProps {
  onIngested: (response: IngestResponse, name: string) => void;
  onError: (name: string, message: string) => void;
  kbName: string;
}

/** Known backend URL error codes that have a localized message key. */
const KNOWN_URL_ERROR_CODES = [
  "invalid_url_format",
  "url_target_forbidden",
  "url_unreachable",
  "url_timeout",
  "url_bad_status",
] as const;

const URL_FORMAT_REGEX = /^https?:\/\/.+/;

/**
 * UrlInputZone — "Submit URL" card: URL input field with instant format
 * validation, submit button, and structured backend error display.
 * Sibling to UploadZone; KB selection and routing live in IngestClient.
 */
export function UrlInputZone({ onIngested, onError, kbName }: UrlInputZoneProps) {
  const t = useTranslations("ingest");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<UrlIngestError | null>(null);
  const ingestUrl = useIngestUrl();

  const trimmed = url.trim();
  const formatInvalid = trimmed.length > 0 && !URL_FORMAT_REGEX.test(trimmed);
  const canSubmit = trimmed.length > 0 && !formatInvalid && !busy;

  function handleUrlChange(value: string) {
    setUrl(value);
    // Clear any prior submit error as soon as the user edits the URL.
    if (submitError) setSubmitError(null);
  }

  async function handleSubmit() {
    if (!canSubmit) return;
    setBusy(true);
    setSubmitError(null);
    try {
      const resp = await ingestUrl.mutateAsync({
        url: trimmed,
        kb_name: kbName || undefined,
      });
      onIngested(resp, trimmed);
      setUrl("");
    } catch (err) {
      const structured = parseUrlIngestError(err);
      if (structured) {
        setSubmitError(structured);
        onError(trimmed, structured.reason);
      } else {
        const message = errorMessage(err);
        setSubmitError({ code: "fallback", reason: message });
        onError(trimmed, message);
      }
    } finally {
      setBusy(false);
    }
  }

  // Resolve the localized error message for the current submitError code,
  // falling back to the generic fallback key when the code is unrecognized.
  function resolveErrorMessage(code: string): string {
    const known = (KNOWN_URL_ERROR_CODES as readonly string[]).includes(code);
    return t(`url.error.${known ? code : "fallback"}`);
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Card header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-semibold text-foreground">{t("url.title")}</h2>
          <span className="inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-semibold text-success">
            <Snowflake className="h-3 w-3" aria-hidden />
            {t("upload.autoDetect")}
          </span>
        </div>
      </div>

      {/* URL input field */}
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
          onChange={(e) => handleUrlChange(e.target.value)}
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

      {/* Instant format validation hint OR submit error box */}
      {formatInvalid ? (
        <p className="flex items-center gap-1.5 text-xs text-danger">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden />
          {t("url.invalidFormat")}
        </p>
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
      ) : null}

      {/* Submit */}
      <Button
        variant="primary"
        size="lg"
        className="w-full font-semibold shadow-[0_4px_16px_-4px_var(--accent)]"
        isDisabled={!canSubmit}
        onPress={() => void handleSubmit()}
      >
        <Globe className="h-4 w-4" aria-hidden />
        {busy ? t("url.submitting") : t("url.submit")}
      </Button>
    </div>
  );
}
