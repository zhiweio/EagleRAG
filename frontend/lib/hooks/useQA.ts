import {
  createSessionApiSessionsPost,
  deleteSessionApiSessionsSessionIdDelete,
  getSessionApiSessionsSessionIdGet,
  listMessagesApiSessionsSessionIdMessagesGet,
  listSessionsApiSessionsGet,
  postQueryQueryPost,
  postSearchSearchPost,
  updateSessionApiSessionsSessionIdPatch,
} from "@/lib/api/generated/sdk.gen";
import type {
  AckResponse,
  MessageListResponse,
  QueryRequest,
  QueryResponse,
  SearchRequest,
  SearchResponse,
  Session,
  SessionListResponse,
  SessionSummary,
} from "@/lib/types";
/**
 * query/session domain hooks: Q&A submission and session management.
 *
 * Queries: useSessions / useSession / useMessages
 * Mutations: useCreateSession / useUpdateSession / useDeleteSession / useQueryAction
 *
 * Note: the Q&A submission hook is named useQueryAction to avoid clashing with
 * @tanstack/react-query's useQuery. queryKey is organised by domain + params so
 * cache is correctly isolated when kb_name changes; successful session mutations
 * invalidate the corresponding query keys to refresh list and detail.
 * Since the backend returns untyped dict, values are asserted via unknown to the
 * target type.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export function useSessions(params?: { limit?: number; offset?: number; kb_name?: string }) {
  return useQuery({
    queryKey: ["sessions", params],
    queryFn: async () => {
      const result = await listSessionsApiSessionsGet({ query: params });
      if (result.error) throw result.error;
      return result.data as unknown as SessionListResponse;
    },
  });
}

export function useSession(sessionId: string) {
  return useQuery({
    queryKey: ["session", sessionId],
    queryFn: async () => {
      const result = await getSessionApiSessionsSessionIdGet({ path: { session_id: sessionId } });
      if (result.error) throw result.error;
      return result.data as unknown as Session;
    },
  });
}

export function useMessages(sessionId: string, params?: { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: ["messages", sessionId, params],
    queryFn: async () => {
      const result = await listMessagesApiSessionsSessionIdMessagesGet({
        path: { session_id: sessionId },
        query: params,
      });
      if (result.error) throw result.error;
      return result.data as unknown as MessageListResponse;
    },
  });
}

export function useCreateSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { title?: string; kb_name?: string }) => {
      const result = await createSessionApiSessionsPost({ body: vars });
      if (result.error) throw result.error;
      return result.data as unknown as SessionSummary;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useUpdateSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { session_id: string; title: string }) => {
      const result = await updateSessionApiSessionsSessionIdPatch({
        path: { session_id: vars.session_id },
        body: { title: vars.title },
      });
      if (result.error) throw result.error;
      return result.data as unknown as SessionSummary;
    },
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      queryClient.invalidateQueries({ queryKey: ["session", vars.session_id] });
    },
  });
}

export function useDeleteSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sessionId: string) => {
      const result = await deleteSessionApiSessionsSessionIdDelete({
        path: { session_id: sessionId },
      });
      if (result.error) throw result.error;
      return result.data as unknown as AckResponse;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useQueryAction() {
  return useMutation({
    mutationFn: async (request: QueryRequest) => {
      const result = await postQueryQueryPost({ body: request });
      if (result.error) throw result.error;
      return result.data as unknown as QueryResponse;
    },
  });
}

/**
 * Pure retrieval (`POST /search`): route → retrieve → sources, no LLM answer.
 *
 * Sources carry the enriched chunk `content` + semantic anchors, so "search
 * mode" renders the evidence rail without generating a response. Accepts the
 * same `scope_filter` / `filters` union as `/query`.
 */
export function useSearch() {
  return useMutation({
    mutationFn: async (request: SearchRequest) => {
      const result = await postSearchSearchPost({ body: request });
      if (result.error) throw result.error;
      return result.data as unknown as SearchResponse;
    },
  });
}
