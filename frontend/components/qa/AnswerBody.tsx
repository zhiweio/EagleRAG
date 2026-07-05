"use client";

import {
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationCardTrigger,
  InlineCitationSource,
} from "@/components/ai-elements/inline-citation";
import { Response, type ResponseProps } from "@/components/ai-elements/response";
import { imageUrl } from "@/lib/api/client";
import { useMemo } from "react";
import { MarkdownSnippet } from "./MarkdownSnippet";
import {
  resolveAnswerImageSrc,
  sourceCitationExcerpt,
  sourceCitationTitle,
  sourceCrumbs,
  sourceString,
} from "./sources-utils";
import type { FlatSource } from "./types";

type MarkdownComponents = NonNullable<ResponseProps["components"]>;

interface AnswerBodyProps {
  content: string;
  /** Flattened sources for this message; used to resolve `[n]` hovercards. */
  flat: FlatSource[];
  /** Focus source `n` in the evidence rail. */
  onCite: (n: number) => void;
  streaming?: boolean;
}

/**
 * Protect fenced/inline code, then rewrite bare `[n]` markers into fragment
 * markdown links (`#cite-n`) so Streamdown keeps them through rehype-sanitize /
 * rehype-harden while our custom anchor renderer turns them into citation badges.
 */
function linkifyCitations(md: string): string {
  const segments = md.split(/(```[\s\S]*?```|`[^`]*`)/g);
  return segments
    .map((seg, i) => (i % 2 === 0 ? seg.replace(/\[(\d{1,3})\]/g, "[$1](#cite-$1)") : seg))
    .join("");
}

function parseCitationIndex(href: string): number | null {
  const legacy = href.startsWith("cite:") ? href.slice(5) : null;
  const fragment = /^#cite-(\d{1,3})$/.exec(href)?.[1] ?? legacy;
  if (!fragment) return null;
  const n = Number.parseInt(fragment, 10);
  return Number.isFinite(n) ? n : null;
}

/** Short provenance line for a citation hovercard (path / page / position). */
function citationSubtitle(item: FlatSource): string {
  if (item.type === "image") {
    const page = sourceString(item.source, "page");
    const position = sourceString(item.source, "position");
    return [page && `p.${page}`, position].filter(Boolean).join(" · ");
  }
  return sourceCrumbs(item.source).join(" › ");
}

/**
 * AnswerBody — the streamed Markdown answer with interactive inline citations.
 *
 * Wraps `Response` (Streamdown) so the answer keeps rich Markdown + code
 * highlighting while `[n]` markers become `InlineCitation` badges: hovering
 * previews the source (file, anchor, excerpt); clicking focuses it in the
 * evidence rail. The blinking caret marks live token streaming.
 */
export function AnswerBody({ content, flat, onCite, streaming = false }: AnswerBodyProps) {
  const linkified = useMemo(() => linkifyCitations(content), [content]);

  const components = useMemo<MarkdownComponents>(
    () => ({
      img: ({ src, alt, className, ...rest }) => {
        const resolved = resolveAnswerImageSrc(
          typeof src === "string" ? src : undefined,
          typeof alt === "string" ? alt : undefined,
          flat,
        );
        if (!resolved) return null;
        const imageAlt =
          typeof alt === "string" && alt.trim() !== "" ? alt : "Answer content image";
        return (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            {...rest}
            alt={imageAlt}
            className={`my-3 max-h-[min(60vh,480px)] w-full rounded-xl border border-border object-contain ${className ?? ""}`}
            loading="lazy"
            src={resolved}
          />
        );
      },
      a: ({ href, children, ...rest }) => {
        const citeIndex = typeof href === "string" ? parseCitationIndex(href) : null;
        if (citeIndex != null) {
          const n = citeIndex;
          const item = flat.find((f) => f.index === n);
          const filename = item ? sourceCitationTitle(item, n) : `#${n}`;
          const subtitle = item ? citationSubtitle(item) : "";
          const excerpt = item ? sourceCitationExcerpt(item) : "";
          const imageId = item?.type === "image" ? sourceString(item.source, "image_id") : "";
          return (
            <InlineCitationCard>
              <InlineCitationCardTrigger label={n} onClick={() => onCite(n)} />
              <InlineCitationCardBody className="w-[min(24rem,92vw)]">
                <InlineCitationSource description={subtitle || undefined} title={filename} />
                {imageId ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    alt=""
                    className="mt-2 max-h-28 w-full rounded-md border border-border bg-background-secondary object-contain"
                    loading="lazy"
                    src={imageUrl(imageId)}
                  />
                ) : null}
                {excerpt ? (
                  <div className="mt-2 max-h-60 overflow-y-auto border-border border-l-2 pl-2 pr-1">
                    <MarkdownSnippet className="text-[11px] not-italic [&_li]:my-0 [&_ol]:my-1 [&_p]:my-1 [&_strong]:font-semibold [&_ul]:my-1">
                      {excerpt}
                    </MarkdownSnippet>
                  </div>
                ) : null}
              </InlineCitationCardBody>
            </InlineCitationCard>
          );
        }
        return (
          <a href={href} rel="noreferrer" target="_blank" {...rest}>
            {children}
          </a>
        );
      },
    }),
    [flat, onCite],
  );

  return (
    <span className="inline">
      <Response components={components}>{linkified}</Response>
      {streaming ? (
        <span
          aria-hidden
          className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-primary align-middle"
        />
      ) : null}
    </span>
  );
}
