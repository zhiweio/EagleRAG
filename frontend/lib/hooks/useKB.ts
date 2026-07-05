import {
  createKnowledgeBaseKnowledgeBasesPost,
  deleteKnowledgeBaseKnowledgeBasesKbNameDelete,
  getKnowledgeBaseKnowledgeBasesKbNameGet,
  kbCollectionsKnowledgeBasesKbNameCollectionsGet,
  kbFacetsKnowledgeBasesKbNameFacetsGet,
  kbFormatDistributionKnowledgeBasesKbNameFormatDistributionGet,
  kbIngestionVolumeKnowledgeBasesKbNameIngestionVolumeGet,
  knowledgeBasesOverviewKnowledgeBasesOverviewGet,
  listKnowledgeBasesKnowledgeBasesGet,
  patchKnowledgeBaseKnowledgeBasesKbNamePatch,
  rebuildKnowledgeBaseKnowledgeBasesKbNameRebuildPost,
} from "@/lib/api/generated/sdk.gen";
import type { KBIconKey, KBStatus, KBTheme, KnowledgeBase } from "@/lib/kb/types";
import type { ScopeFacets } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export type KBSort = "recent" | "name" | "size";

type ApiKB = Record<string, unknown>;

function mapKbItem(raw: ApiKB): KnowledgeBase {
  const updatedAt = raw.updated_at as string | undefined;
  const updatedAgoMs = updatedAt ? Math.max(0, Date.now() - new Date(updatedAt).getTime()) : 0;
  const kpi = raw.kpi as ApiKB | undefined;
  return {
    kbName: String(raw.kb_name ?? ""),
    displayName: String(raw.display_name ?? raw.kb_name ?? ""),
    description: String(raw.description ?? ""),
    theme: (raw.theme as KBTheme) ?? "blue",
    icon: (raw.icon as KBIconKey) ?? "landmark",
    pdfTextPageRatio: Number(raw.pdf_text_page_ratio ?? 0.2),
    documents: Number(kpi?.documents ?? raw.documents ?? 0),
    graphNodes: Number(kpi?.graph_nodes ?? raw.graph_nodes ?? 0),
    visualSlices: Number(kpi?.visual_slices ?? raw.visual_slices ?? 0),
    queries7d: Number(kpi?.queries_7d ?? raw.queries_7d ?? 0),
    activeIngestions: Number(raw.active_ingestions ?? 0),
    collections: Array.isArray(raw.collections) ? (raw.collections as string[]) : [],
    status: raw.status ? (String(raw.status) as KBStatus) : undefined,
    updatedAgoMs,
    recent: updatedAgoMs < 3 * 24 * 60 * 60 * 1000,
  };
}

export function useKnowledgeBases(params?: {
  query?: string;
  sort?: KBSort;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["knowledge_bases", params],
    queryFn: async () => {
      const result = await listKnowledgeBasesKnowledgeBasesGet({
        query: {
          query: params?.query,
          sort: params?.sort ?? "recent",
          limit: params?.limit ?? 50,
          offset: params?.offset ?? 0,
        },
      });
      if (result.error) throw result.error;
      const data = result.data as { items?: ApiKB[]; total?: number };
      return {
        items: (data.items ?? []).map(mapKbItem),
        total: data.total ?? 0,
      };
    },
  });
}

export function useKBOverview() {
  return useQuery({
    queryKey: ["knowledge_bases", "overview"],
    queryFn: async () => {
      const result = await knowledgeBasesOverviewKnowledgeBasesOverviewGet();
      if (result.error) throw result.error;
      const d = result.data as ApiKB;
      return {
        kbCount: Number(d.kb_count ?? 0),
        activeIngestions: Number(d.active_ingestions ?? 0),
        totalDocuments: Number(d.total_documents ?? 0),
        totalGraphNodes: Number(d.total_graph_nodes ?? 0),
        totalVectors: Number(d.total_vectors ?? 0),
      };
    },
  });
}

export function useKnowledgeBase(kbName: string) {
  return useQuery({
    queryKey: ["knowledge_base", kbName],
    queryFn: async () => {
      const result = await getKnowledgeBaseKnowledgeBasesKbNameGet({
        path: { kb_name: kbName },
      });
      if (result.error) throw result.error;
      return mapKbItem(result.data as ApiKB);
    },
    enabled: Boolean(kbName),
  });
}

export function useKBFormatDistribution(kbName: string) {
  return useQuery({
    queryKey: ["kb_format_distribution", kbName],
    queryFn: async () => {
      const result = await kbFormatDistributionKnowledgeBasesKbNameFormatDistributionGet({
        path: { kb_name: kbName },
      });
      if (result.error) throw result.error;
      const d = result.data as {
        segments?: Array<{ key: string; label: string; value: number; color: string }>;
      };
      return d.segments ?? [];
    },
    enabled: Boolean(kbName),
  });
}

export function useKBIngestionVolume(kbName: string, days = 7) {
  return useQuery({
    queryKey: ["kb_ingestion_volume", kbName, days],
    queryFn: async () => {
      const result = await kbIngestionVolumeKnowledgeBasesKbNameIngestionVolumeGet({
        path: { kb_name: kbName },
        query: { days },
      });
      if (result.error) throw result.error;
      return result.data as {
        unit: string;
        peak: number;
        points: Array<{ date: string; label: string; value: number }>;
      };
    },
    enabled: Boolean(kbName),
  });
}

export function useKBCollections(kbName: string) {
  return useQuery({
    queryKey: ["kb_collections", kbName],
    queryFn: async () => {
      const result = await kbCollectionsKnowledgeBasesKbNameCollectionsGet({
        path: { kb_name: kbName },
      });
      if (result.error) throw result.error;
      const d = result.data as {
        collections?: Array<{
          name: string;
          model: string;
          dim: number;
          index: string;
          entities: number;
          capacity_ratio: number;
        }>;
      };
      return d.collections ?? [];
    },
    enabled: Boolean(kbName),
  });
}

export function useKBFacets(kbName?: string) {
  return useQuery({
    queryKey: ["kb_facets", kbName],
    queryFn: async () => {
      const result = await kbFacetsKnowledgeBasesKbNameFacetsGet({
        path: { kb_name: kbName ?? "" },
      });
      if (result.error) throw result.error;
      return result.data as ScopeFacets;
    },
    enabled: Boolean(kbName),
  });
}

export function useCreateKB() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      kb_name: string;
      display_name: string;
      description?: string;
      theme?: string;
      icon?: string;
      pdf_text_page_ratio?: number;
    }) => {
      const result = await createKnowledgeBaseKnowledgeBasesPost({ body });
      if (result.error) throw result.error;
      return mapKbItem(result.data as ApiKB);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge_bases"] });
    },
  });
}

export function useUpdateKB() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: {
      kb_name: string;
      display_name?: string;
      description?: string;
      theme?: string;
      icon?: string;
      pdf_text_page_ratio?: number;
    }) => {
      const { kb_name, ...body } = vars;
      const result = await patchKnowledgeBaseKnowledgeBasesKbNamePatch({
        path: { kb_name },
        body,
      });
      if (result.error) throw result.error;
      return mapKbItem(result.data as ApiKB);
    },
    onSuccess: (_d, vars) => {
      queryClient.invalidateQueries({ queryKey: ["knowledge_bases"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge_base", vars.kb_name] });
    },
  });
}

export function useDeleteKB() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (kbName: string) => {
      const result = await deleteKnowledgeBaseKnowledgeBasesKbNameDelete({
        path: { kb_name: kbName },
      });
      if (result.error) throw result.error;
      return result.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge_bases"] });
    },
  });
}

export function useRebuildKB() {
  return useMutation({
    mutationFn: async (kbName: string) => {
      const result = await rebuildKnowledgeBaseKnowledgeBasesKbNameRebuildPost({
        path: { kb_name: kbName },
      });
      if (result.error) throw result.error;
      return result.data as { job_id: string };
    },
  });
}
