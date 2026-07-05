import {
  deleteDocumentApiDocumentsDocumentIdDelete,
  getDocumentApiDocumentsDocumentIdGet,
  getDocumentStructureApiDocumentsDocumentIdStructureGet,
  getImageMetaApiImagesImageIdMetaGet,
  listDocumentsApiDocumentsGet,
} from "@/lib/api/generated/sdk.gen";
import type {
  AckResponse,
  Document,
  DocumentListParams,
  DocumentListResponse,
  DocumentStructureOut,
  ImageMeta,
} from "@/lib/types";
/**
 * documents domain hooks: document list, single lookup, deletion and image metadata.
 *
 * queryKey is organised by domain + params so cache is correctly isolated when
 * filters such as kb_name change; useDeleteDocument invalidates ["documents"] on
 * success to refresh the list.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export function useDocuments(params?: DocumentListParams) {
  return useQuery({
    queryKey: ["documents", params],
    queryFn: async () => {
      const result = await listDocumentsApiDocumentsGet({ query: params });
      if (result.error) throw result.error;
      return result.data as DocumentListResponse;
    },
  });
}

export function useDocument(documentId: string) {
  return useQuery({
    queryKey: ["document", documentId],
    queryFn: async () => {
      const result = await getDocumentApiDocumentsDocumentIdGet({
        path: { document_id: documentId },
      });
      if (result.error) throw result.error;
      return result.data as Document;
    },
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (documentId: string) => {
      const result = await deleteDocumentApiDocumentsDocumentIdDelete({
        path: { document_id: documentId },
      });
      if (result.error) throw result.error;
      return result.data as AckResponse;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useImageMeta(imageId: string) {
  return useQuery({
    queryKey: ["image-meta", imageId],
    queryFn: async () => {
      const result = await getImageMetaApiImagesImageIdMetaGet({ path: { image_id: imageId } });
      if (result.error) throw result.error;
      return result.data as ImageMeta;
    },
  });
}

/**
 * Fetch a document's parsed semantic tree (Knowhere `doc_nav` sections + visual
 * anchors) for the evidence Document Structure viewer.
 *
 * Disabled until `documentId` is set so opening the viewer drives the fetch; the
 * result is cached per document so switching between citations is instant.
 */
export function useDocumentStructure(documentId: string | null | undefined) {
  return useQuery({
    queryKey: ["document-structure", documentId],
    enabled: Boolean(documentId),
    staleTime: 5 * 60 * 1000,
    queryFn: async () => {
      const result = await getDocumentStructureApiDocumentsDocumentIdStructureGet({
        path: { document_id: documentId as string },
      });
      if (result.error) throw result.error;
      return result.data as DocumentStructureOut;
    },
  });
}
