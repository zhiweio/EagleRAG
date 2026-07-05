"use client";

import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type ImageProps = Omit<ComponentProps<"img">, "src"> & {
  base64?: string;
  mediaType?: string;
  src?: string;
};

/**
 * Renders a generated or retrieved image from either a direct `src` URL or an
 * inline `base64` + `mediaType` pair (data URI).
 */
export function Image({ base64, mediaType, src, alt = "", className, ...props }: ImageProps) {
  const resolved = src ?? (base64 && mediaType ? `data:${mediaType};base64,${base64}` : undefined);
  if (!resolved) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    // biome-ignore lint/a11y/useAltText: alt is caller-provided; "" denotes a decorative image
    <img
      alt={alt}
      className={cn("h-auto max-w-full overflow-hidden rounded-md", className)}
      src={resolved}
      {...props}
    />
  );
}
