import { listTagsApiTagsGet } from "@/lib/api/generated/sdk.gen";
import type { TagListResponse } from "@/lib/api/generated/types.gen";
/**
 * Tag (keyword) catalog hook. Backs the scope filter's tag dimension: lists
 * keyword tags with hit counts / KB coverage, filterable by search text and
 * knowledge bases. queryKey includes q + kbNames so the react-query cache is
 * isolated per filter.
 */
import { useQuery } from "@tanstack/react-query";

export function useTags(params?: { q?: string; kbNames?: string[]; limit?: number }) {
  const q = params?.q;
  const kbNames = params?.kbNames;
  const limit = params?.limit ?? 30;
  return useQuery({
    queryKey: ["tags", q, kbNames, limit],
    queryFn: async () => {
      const result = await listTagsApiTagsGet({
        query: {
          q: q || undefined,
          kb_names: kbNames && kbNames.length > 0 ? kbNames : undefined,
          limit,
        },
      });
      if (result.error) throw result.error;
      return result.data as TagListResponse;
    },
  });
}
