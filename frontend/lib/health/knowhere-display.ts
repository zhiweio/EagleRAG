import type { ServiceChip } from "@/lib/health/types";

export type KnowhereMode = "api" | "parser";

export function resolveKnowhereMode(mode?: string | null): KnowhereMode {
  return mode === "parser" ? "parser" : "api";
}

type ChipT = (key: string, values?: Record<string, string | number>) => string;

/** Map ``kb_name`` to a partition tag; unknown names use the generic ``kb`` tag. */
export function kbPartitionTagKey(kbName: string): "patent" | "finance" | "kb" {
  const normalized = kbName.trim().toLowerCase();
  if (normalized === "finance" || normalized.includes("finance")) return "finance";
  if (normalized === "patent" || normalized.includes("patent")) return "patent";
  return "kb";
}

/** Build up to two localized metric chips for the Knowhere service card. */
export function knowhereChipsFromDetail(
  detail: string | undefined,
  mode: KnowhereMode,
  t: ChipT,
): ServiceChip[] {
  const chips: ServiceChip[] = [
    {
      label: t(mode === "api" ? "knowhereChips.modeApi" : "knowhereChips.modeParser"),
      tone: "accent",
    },
  ];

  if (mode === "api") {
    const statusCode = detail?.match(/status_code=(\d+)/)?.[1];
    if (statusCode) {
      chips.push({
        label: t("knowhereChips.statusCode", { code: statusCode }),
        tone: statusCode.startsWith("2") ? "success" : "warning",
      });
    }
  } else {
    const mineru = detail?.match(/mineru=(configured|not configured)/)?.[1];
    if (mineru) {
      chips.push({
        label: t(
          mineru === "configured"
            ? "knowhereChips.mineruConfigured"
            : "knowhereChips.mineruNotConfigured",
        ),
        tone: mineru === "configured" ? "success" : "warning",
      });
    }
  }

  return chips.slice(0, 2);
}

/** Extract ``tmp_path`` from a parser-mode probe detail string. */
export function parserTmpPathFromDetail(detail?: string | null): string | null {
  const match = detail?.match(/tmp_path=([^,]+)/)?.[1]?.trim();
  return match || null;
}
