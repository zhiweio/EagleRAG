"use client";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Download, ExternalLink, Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import type { PreviewLayout } from "./types";

interface DocumentPreviewShellProps {
  title: string;
  href?: string;
  layout: PreviewLayout;
  onZoom?: () => void;
  children: React.ReactNode;
}

/** Shared chrome: title bar with zoom, open-in-new-tab, and download affordances. */
export function DocumentPreviewShell({
  title,
  href,
  layout,
  onZoom,
  children,
}: DocumentPreviewShellProps) {
  const t = useTranslations("documentPreview");
  const showZoom = layout !== "modal" && onZoom;
  const showTitle = layout !== "modal";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-separator bg-surface shadow-xs">
      {showTitle || showZoom || href ? (
        <header className="flex h-9 shrink-0 items-center gap-2 border-separator/80 border-b bg-(--surface-muted)/40 px-2.5">
          {showTitle ? (
            <p
              className="min-w-0 flex-1 truncate font-medium text-foreground text-xs leading-none"
              title={title}
            >
              {title}
            </p>
          ) : (
            <span className="min-w-0 flex-1" />
          )}
          <div className="flex shrink-0 items-center gap-0.5">
            {showZoom ? (
              <ShellIconButton label={t("zoom")} onClick={onZoom}>
                <Maximize2 size={14} strokeWidth={2.2} aria-hidden />
              </ShellIconButton>
            ) : null}
            {href ? (
              <>
                <ShellIconLink label={t("openNewTab")} href={href}>
                  <ExternalLink size={14} strokeWidth={2} aria-hidden />
                </ShellIconLink>
                <ShellIconLink label={t("download")} href={href} download={title}>
                  <Download size={14} strokeWidth={2} aria-hidden />
                </ShellIconLink>
              </>
            ) : null}
          </div>
        </header>
      ) : null}
      <div className="min-h-0 flex-1 overflow-hidden p-1">{children}</div>
    </div>
  );
}

function ShellIconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={label}
          onClick={onClick}
          className="text-foreground-tertiary hover:text-foreground"
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

function ShellIconLink({
  label,
  href,
  download,
  children,
}: {
  label: string;
  href: string;
  download?: string;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          asChild
          className="text-foreground-tertiary hover:text-foreground"
        >
          <a
            href={href}
            download={download}
            rel="noreferrer"
            target={download ? undefined : "_blank"}
            aria-label={label}
          >
            {children}
          </a>
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}
