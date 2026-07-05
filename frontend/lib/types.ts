/**
 * Domain type aliases: all derived from OpenAPI generated types.
 */
import type {
  ListDocumentsApiDocumentsGetData,
  ListTasksTasksGetData,
  TaskAuditOut,
} from "./api/generated/types.gen";

export type {
  AdminCeleryResponse,
  AdminCeleryResponse as AdminCeleryInfo,
  AdminConfigOut,
  AdminConfigOut as AdminConfig,
  AdminKnowhereResponse,
  AdminKnowhereResponse as AdminKnowhereInfo,
  AdminMcpResponse,
  AdminMcpResponse as AdminMcpInfo,
  AdminMilvusResponse,
  AdminMilvusResponse as AdminMilvusInfo,
  AdminPixelragResponse,
  AdminPixelragResponse as AdminPixelRagInfo,
  AdminProbesResponse,
  AdminVlmResponse,
  AdminVlmResponse as AdminVlmInfo,
  DeletedResponse as AckResponse,
  DependencyStatus,
  DependencyStatus as DependencyState,
  DependencySummary,
  DocumentListResponse,
  DocumentOut,
  DocumentOut as Document,
  DocumentStructureNode,
  DocumentStructureOut,
  DocumentVisualRef,
  HealthResponse,
  ImageMetaOut,
  ImageMetaOut as ImageMeta,
  IngestResponse,
  KbFacetsResponse,
  KbFacetsResponse as ScopeFacets,
  McpToolDefinition,
  McpToolDefinition as McpTool,
  McpToolsResponse,
  MessageListResponse,
  MessageOut,
  MessageOut as Message,
  ProbeDetail,
  ProbeDetail as ProbeInfo,
  QueryFilters,
  QueryRequest,
  QueryResponse,
  QuerySources,
  QueryStep,
  QueryStep as Step,
  RouteInfo,
  ScopeSelection,
  SearchRequest,
  SearchResponse,
  SessionCreate,
  SessionListResponse,
  SessionSummary,
  SessionSummary as Session,
  TaskAuditOut,
  TaskListResponse,
  TaskLogEntry,
  TaskLogEntry as TaskLog,
  TaskLogsResponse,
  TaskRetryResponse,
  TextSource,
  ImageSource,
  UserOut,
  UserPreferences,
} from "./api/generated/types.gen";

export type Task = TaskAuditOut & {
  name?: string | null;
  source_uri?: string | null;
};

export type DocumentListParams = NonNullable<ListDocumentsApiDocumentsGetData["query"]>;
export type TaskListParams = NonNullable<ListTasksTasksGetData["query"]>;

export type SourceType = "policy" | "financial" | "business" | "bidding" | "tax" | "other";
