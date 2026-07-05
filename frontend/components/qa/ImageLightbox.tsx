"use client";

import { imageUrl } from "@/lib/api/client";
import { getImageMetaApiImagesImageIdMetaGet } from "@/lib/api/generated/sdk.gen";
import { useUIStore } from "@/lib/stores/uiStore";
import type { ImageMeta } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Modal, Spinner } from "@heroui/react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

/**
 * Image preview lightbox. The currently shown imageId and the close action come
 * from useUIStore, letting any location (SourcesCard / MessageBubble, etc.) open
 * it via setQaLightboxImageId. Metadata is fetched best-effort (the image still
 * renders when the DB is unavailable).
 */
export function ImageLightbox() {
  const t = useTranslations("qa.lightbox");
  const imageId = useUIStore((s) => s.qaLightboxImageId);
  const setQaLightboxImageId = useUIStore((s) => s.setQaLightboxImageId);
  const [meta, setMeta] = useState<ImageMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const isOpen = imageId !== null;

  useEffect(() => {
    if (!imageId) {
      setMeta(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setMeta(null);
    getImageMetaApiImagesImageIdMetaGet({ path: { image_id: imageId } })
      .then((result) => {
        if (result.error) throw result.error;
        if (!cancelled) setMeta(result.data ?? null);
      })
      .catch(() => {
        // metadata is best-effort; the image can still render without it
        if (!cancelled) setMeta(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [imageId]);

  return (
    <Modal isOpen={isOpen} onOpenChange={(open) => !open && setQaLightboxImageId(null)}>
      <Modal.Backdrop className="bg-black/80 backdrop-blur-md">
        <Modal.Container size="full" scroll="inside">
          <Modal.Dialog className="relative border-0 bg-transparent p-0 text-white shadow-none">
            <Modal.CloseTrigger
              aria-label={t("close")}
              className={cn(
                "absolute top-4 right-4 z-20 inline-flex size-9 items-center justify-center rounded-full",
                "border-0 bg-transparent p-0 shadow-none outline-none",
                "text-white/75 transition-[color,background-color,opacity] duration-150",
                "hover:bg-white/12 hover:text-white",
                "focus-visible:ring-2 focus-visible:ring-white/35 focus-visible:ring-offset-0",
              )}
            >
              <X size={20} strokeWidth={1.75} aria-hidden />
            </Modal.CloseTrigger>
            <Modal.Body className="flex min-h-full flex-col items-center justify-center gap-3 p-4 pt-14">
              {imageId && (
                <div className="flex flex-col items-center gap-3">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={imageUrl(imageId)}
                    alt={t("title")}
                    className="max-h-[70vh] w-auto max-w-full rounded-2xl border border-white/10 object-contain shadow-2xl"
                  />
                  <div className="w-full max-w-2xl text-xs">
                    <p className="mb-1 font-semibold text-white/60">{t("meta")}</p>
                    {loading ? (
                      <Spinner size="sm" />
                    ) : meta ? (
                      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
                        <MetaRow k="document_id" v={meta.document_id} />
                        <MetaRow k="page" v={meta.page} />
                        <MetaRow k="position" v={meta.position} />
                        <MetaRow k="width" v={meta.width} />
                        <MetaRow k="height" v={meta.height} />
                      </dl>
                    ) : (
                      <code className="break-all text-white/60">{imageId}</code>
                    )}
                  </div>
                </div>
              )}
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

function MetaRow({ k, v }: { k: string; v: unknown }) {
  if (v === undefined || v === null || v === "") return null;
  return (
    <div className="contents">
      <dt className="font-medium text-white/80">{k}</dt>
      <dd className="text-white/60">{String(v)}</dd>
    </div>
  );
}
