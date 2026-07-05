"use client";

import { Link, useRouter } from "@/i18n/routing";
import { useDeleteKB } from "@/lib/hooks/useKB";
import type { KnowledgeBase } from "@/lib/kb/types";
import { formatRelative } from "@/lib/kb/types";
import { Popover } from "@heroui/react";
import {
  EllipsisVertical,
  FileText,
  Image as ImageIcon,
  Settings2,
  Share2,
  Trash2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { EditKBDrawer } from "./EditKBDrawer";
import { useKBToast } from "./KBToast";
import { PurgeConfirmModal } from "./PurgeConfirmModal";
import { CollectionTag, KBBadge } from "./kb-visuals";

function Metric({ value, icon: Icon, label }: { value: number; icon: LucideIcon; label: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-1">
      <span
        className="font-mono text-xl font-bold tracking-tight text-foreground"
        style={{ letterSpacing: "-0.3px" }}
      >
        {value.toLocaleString()}
      </span>
      <span className="flex items-center gap-1 text-[11px]">
        <Icon className="h-3 w-3 text-foreground-tertiary" aria-hidden />
        <span className="font-medium text-foreground-tertiary">{label}</span>
      </span>
    </div>
  );
}

export function KBCard({ kb }: { kb: KnowledgeBase }) {
  const t = useTranslations("kb.card");
  const tToast = useTranslations("kb.toast");
  const locale = useLocale();
  const router = useRouter();
  const deleteKB = useDeleteKB();
  const { pushToast } = useKBToast();

  const [purgeOpen, setPurgeOpen] = useState(false);
  const [purgeError, setPurgeError] = useState<Error | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const openPurge = () => {
    setPurgeError(null);
    setPurgeOpen(true);
  };

  const confirmPurge = () => {
    setPurgeError(null);
    deleteKB.mutate(kb.kbName, {
      onSuccess: () => {
        setPurgeOpen(false);
        pushToast({ variant: "success", title: tToast("deleted") });
      },
      onError: (err) => {
        setPurgeError(err);
      },
    });
  };

  return (
    <div className="group relative flex flex-col gap-4 rounded-2xl border border-border bg-surface p-[18px] shadow-[0_2px_8px_0_rgba(0,0,0,0.04)] transition-[border-color,box-shadow] hover:border-accent/60 hover:shadow-[0_8px_24px_0_rgba(4,133,247,0.10)]">
      <Popover>
        <Popover.Trigger>
          <button
            type="button"
            aria-label={t("more")}
            className="absolute right-3 top-3 z-10 flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-tertiary transition-colors hover:bg-background-secondary hover:text-foreground"
          >
            <EllipsisVertical className="h-[17px] w-[17px]" aria-hidden />
          </button>
        </Popover.Trigger>
        <Popover.Content className="min-w-40 p-1">
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-background-secondary"
            onClick={() => router.push(`/kb/${kb.kbName}` as "/kb")}
          >
            {t("open")}
          </button>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-background-secondary"
            onClick={() => setEditOpen(true)}
          >
            <Settings2 className="h-4 w-4" aria-hidden />
            {t("edit")}
          </button>
          <button
            type="button"
            disabled={deleteKB.isPending}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-danger hover:bg-danger/10"
            onClick={openPurge}
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            {t("delete")}
          </button>
        </Popover.Content>
      </Popover>

      <Link
        href={`/kb/${kb.kbName}`}
        aria-label={`${t("open")}: ${kb.displayName}`}
        className="flex flex-col gap-4 rounded-xl outline-none focus-visible:ring-4 focus-visible:ring-accent/25"
      >
        <div className="flex items-center gap-3 pr-8">
          <KBBadge theme={kb.theme} icon={kb.icon} />
          <div className="flex min-w-0 flex-1 flex-col gap-[3px]">
            <span className="truncate text-base font-semibold text-foreground">
              {kb.displayName}
            </span>
            <span className="truncate font-mono text-xs font-medium text-foreground-tertiary">
              {kb.kbName}
            </span>
          </div>
        </div>

        <div className="flex items-center rounded-xl bg-(--surface-muted) px-1 py-[13px]">
          <Metric value={kb.documents} icon={FileText} label={t("docs")} />
          <span className="h-[30px] w-px bg-separator" aria-hidden />
          <Metric value={kb.graphNodes} icon={Share2} label={t("nodes")} />
          <span className="h-[30px] w-px bg-separator" aria-hidden />
          <Metric value={kb.visualSlices} icon={ImageIcon} label={t("slices")} />
        </div>

        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {kb.collections
              .filter((name) => name !== "eagle_visual" || kb.visualSlices > 0)
              .map((name) => (
                <CollectionTag key={name} name={name} />
              ))}
          </div>
          <span className="shrink-0 text-[11px] text-foreground-tertiary">
            {formatRelative(kb.updatedAgoMs, locale)}
          </span>
        </div>
      </Link>

      <EditKBDrawer kb={kb} isOpen={editOpen} onOpenChange={setEditOpen} />
      <PurgeConfirmModal
        kb={kb}
        isOpen={purgeOpen}
        onOpenChange={setPurgeOpen}
        onConfirm={confirmPurge}
        isPending={deleteKB.isPending}
        error={purgeError}
      />
    </div>
  );
}
