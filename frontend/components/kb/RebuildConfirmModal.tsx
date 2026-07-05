"use client";

import type { KnowledgeBase } from "@/lib/kb/types";
import { Modal } from "@heroui/react";
import { AlertTriangle, Check, RefreshCw, X } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * RebuildConfirmModal — secondary confirmation modal for rebuilding a knowledge
 * base index. Replaces the native window.confirm with a centred HeroUI v3 Modal,
 * consistent with the system style. Rebuilding is non-destructive (the original
 * documents are kept), so it uses the amber/warning tone instead of danger.
 */
export function RebuildConfirmModal({
  kb,
  isOpen,
  onOpenChange,
  onConfirm,
  isPending,
}: {
  kb: KnowledgeBase;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  isPending: boolean;
}) {
  const t = useTranslations("kb.detail.rebuildModal");

  const handleConfirm = () => {
    onConfirm();
  };

  return (
    <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Backdrop className="bg-black/40 backdrop-blur-sm data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
        <Modal.Container>
          <Modal.Dialog
            aria-label={t("title")}
            className="w-[460px] max-w-[92vw] overflow-hidden rounded-2xl bg-surface shadow-[0_24px_80px_-12px_rgba(0,0,0,0.32)] data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]"
          >
            {/* Header */}
            <Modal.Header className="flex items-start justify-between gap-3 border-b border-separator px-5 py-4">
              <div className="flex items-center gap-3">
                <span className="flex h-[40px] w-[40px] shrink-0 items-center justify-center rounded-xl bg-amber-100">
                  <AlertTriangle className="h-5 w-5 text-amber-600" aria-hidden />
                </span>
                <div className="flex flex-col gap-0.5">
                  <Modal.Heading className="text-[16px] font-semibold leading-tight text-foreground">
                    {t("title")}
                  </Modal.Heading>
                  <span className="font-mono text-[11px] text-foreground-tertiary">
                    {t("subtitle", { name: kb.kbName })}
                  </span>
                </div>
              </div>
              <Modal.CloseTrigger
                aria-label={t("close")}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-foreground-tertiary transition-colors hover:bg-background-secondary hover:text-foreground"
              >
                <X className="h-4 w-4" aria-hidden />
              </Modal.CloseTrigger>
            </Modal.Header>

            {/* Body */}
            <Modal.Body className="flex flex-col gap-3 px-5 py-5">
              <p className="text-sm leading-relaxed text-foreground-secondary">{t("desc")}</p>
              <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-3.5 py-3">
                <RefreshCw
                  className="mt-0.5 h-[14px] w-[14px] shrink-0 text-amber-600"
                  aria-hidden
                />
                <p className="text-[12px] leading-relaxed text-amber-800">{t("hint")}</p>
              </div>
            </Modal.Body>

            {/* Footer */}
            <Modal.Footer className="flex items-center justify-end gap-2.5 border-t border-separator px-5 py-4">
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                disabled={isPending}
                className="flex h-[42px] items-center justify-center rounded-xl border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:bg-(--surface-muted) disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={isPending}
                className="flex h-[42px] items-center justify-center gap-2 rounded-xl bg-amber-600 px-5 text-sm font-semibold text-white shadow-[0_5px_14px_0_rgba(217,119,6,0.28)] transition-colors hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isPending ? (
                  <>
                    <RefreshCw className="h-[17px] w-[17px] animate-spin" aria-hidden />
                    <span>{t("confirm")}</span>
                  </>
                ) : (
                  <>
                    <Check className="h-[17px] w-[17px]" aria-hidden />
                    {t("confirm")}
                  </>
                )}
              </button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
