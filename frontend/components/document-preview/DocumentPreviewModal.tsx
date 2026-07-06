"use client";

import { DocumentPreview } from "@/components/document-preview/DocumentPreview";
import { previewContentUrl, previewTitle } from "@/components/document-preview/preview-urls";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { usePreviewStore } from "@/lib/stores/previewStore";
import { Modal } from "@heroui/react";
import { Download, ExternalLink, X } from "lucide-react";
import { useTranslations } from "next-intl";

/** Global fullscreen document preview modal. Mount once in the app shell. */
export function DocumentPreviewModal() {
  const t = useTranslations("documentPreview");
  const target = usePreviewStore((s) => s.modalTarget);
  const closePreview = usePreviewStore((s) => s.closePreview);
  const isOpen = target !== null;
  const title = target ? previewTitle(target) : t("title");
  const href = target ? previewContentUrl(target) : undefined;

  return (
    <Modal isOpen={isOpen} onOpenChange={(open) => !open && closePreview()}>
      <Modal.Backdrop className="bg-black/40 backdrop-blur-sm data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
        <Modal.Container>
          <Modal.Dialog
            aria-label={title}
            className="flex h-[min(94vh,960px)] w-[min(1240px,96vw)] max-w-[96vw] flex-col overflow-hidden rounded-2xl bg-surface shadow-[0_24px_80px_-12px_rgba(0,0,0,0.32)] data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]"
          >
            <header className="flex h-11 shrink-0 items-center gap-2 border-separator border-b px-3 sm:px-4">
              <p
                className="min-w-0 flex-1 truncate font-medium text-[13px] text-foreground leading-none"
                title={title}
              >
                {title}
              </p>
              <div className="flex shrink-0 items-center gap-0.5">
                {href ? (
                  <>
                    <ModalActionLink label={t("openNewTab")} href={href}>
                      <ExternalLink size={15} strokeWidth={2} aria-hidden />
                    </ModalActionLink>
                    <ModalActionLink label={t("download")} href={href} download={title}>
                      <Download size={15} strokeWidth={2} aria-hidden />
                    </ModalActionLink>
                  </>
                ) : null}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("close")}
                      onClick={closePreview}
                      className="text-foreground-tertiary hover:text-foreground"
                    >
                      <X size={16} strokeWidth={2} aria-hidden />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">{t("close")}</TooltipContent>
                </Tooltip>
              </div>
            </header>
            <Modal.Body className="min-h-0 flex-1 overflow-hidden p-0">
              {target ? (
                <DocumentPreview target={target} layout="modal" className="h-full" />
              ) : null}
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

function ModalActionLink({
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
        <Button variant="ghost" size="icon-sm" asChild className="text-foreground-tertiary">
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
