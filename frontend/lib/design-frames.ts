/**
 * Pencil design frames (18 artboards) for Phase 7 page implementation.
 *
 * Branding notes (must be respected when implementing these frames):
 * - Frame `qniEp` (02) shows "Nexus RAG" in the source design — render as "Eagle-RAG".
 * - Frame `u4gijt` (03) contains a Theme Btn in the source design — do NOT implement it
 *   (light theme only).
 */

export interface DesignFrame {
  id: string;
  name: string;
}

export const DESIGN_FRAMES: DesignFrame[] = [
  { id: "m69sPX", name: "01 · 多模态问答与溯源" },
  { id: "qniEp", name: "02 · 摄入与路由" },
  { id: "u4gijt", name: "03 · MCP 与服务健康" },
  { id: "H4Zxmw", name: "04 · Drawer · Celery Workers" },
  { id: "cYasM", name: "05 · Drawer · Milvus & PixelRAG" },
  { id: "mjOkV", name: "06 · Drawer · VLM / LLM" },
  { id: "VG5ti", name: "07 · Drawer · MCP Server" },
  { id: "K15ctu", name: "08 · Drawer · Live Logs" },
  { id: "brACk", name: "12 · Drawer · Config & Probes" },
  { id: "J9bkio", name: "09 · Modal · Task Logs" },
  { id: "or60l", name: "11 · Modal · Task Logs Success" },
  { id: "P94oMq", name: "Toast · 摄入成功" },
  { id: "Yh1bN", name: "10 · Filter Popovers" },
  { id: "cDTyI", name: "01+ · 附件与 @ 自动补全" },
  { id: "sZfG2", name: "01+ · 思考/检索步骤" },
  { id: "PkLxA", name: "01+ · 引用高亮联动" },
  { id: "siadn", name: "01+ · 图片 Lightbox" },
  { id: "F2XqKJ", name: "01+ · 历史会话抽屉" },
];
