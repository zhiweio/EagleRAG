# 知识库模块

租户管理 UI：`/kb` 与 `/kb/[kbName]`。组件在 `components/kb/`。

---

## 列表页（`/kb`）

`KBManagementClient.tsx` 编排：

| 组件 | 角色 |
|-----------|------|
| `KBGhostCard` | 创建 KB 占位卡片 |
| `CreateKBDrawer` | `POST /knowledge_bases` 表单 |
| `KBToast` | 成功/错误反馈 |
| 概览图表 | `GET /knowledge_bases/overview` |

### KB 卡片

每张卡片显示 `KBItem` 统计：文档、图节点、视觉切片、活跃入库、主题色板（`ThemeSwatchPicker` 模式）。

导航 → `/kb/{kb_name}`。

### Hooks

`lib/hooks/useKB.ts` 中的 `useKnowledgeBases`、`useKBOverview`。

Query keys：

```
["knowledge-bases", params]
["knowledge-bases", "overview"]
```

---

## 详情页（`/kb/[kbName]`）

`KBDetailClient.tsx` —— 单命名空间深入视图。

### KPI 头

`GET /knowledge_bases/{kb_name}` → `KBDetailOut`：

- `status` 徽章（`healthy` / `degraded`）
- `kpi.documents`、`graph_nodes`、`visual_slices`、`queries_7d`

### 图表（`kb-charts.tsx`）

| 图表 | 端点 |
|-------|----------|
| 格式分布 | `GET …/format-distribution` |
| 入库量 | `GET …/ingestion-volume?days=7` |

Recharts 柱/面积图，颜色来自 KB `theme` token。

### Milvus 面板（`MilvusCollectionCard.tsx`）

`GET …/collections` —— `eagle_text` / `eagle_visual` 行数。

### 分面

`GET …/facets` —— 内嵌文档列表的过滤芯片。

### 破坏性操作

| 模态 | API |
|-------|-----|
| `PurgeConfirmModal` | `DELETE /knowledge_bases/{kb_name}` |
| `RebuildConfirmModal` | `POST …/rebuild` |
| `DocumentDeleteModal` | `DELETE /documents/{id}` |

### 编辑元数据

`EditKBDrawer` → `PATCH /knowledge_bases/{kb_name}`。

---

## 视觉系统（`kb-visuals.tsx`）

将 `theme` + `icon` 字段映射到 Tailwind 色类与 Lucide 图标 —— 列表与详情卡片身份一致。

---

## 类型（`lib/kb/types.ts`）

重导出 / 收窄 KB 领域的生成 OpenAPI 类型。

---

## 多租户 UX 说明

- URL 中 `kb_name` 为规范标识（小写 + 下划线）
- 入库页用 `TargetKBSelector` —— 与问答 `scopeStore` 分离
- 问答 scope 抽屉可通过 `scope_filter.kb_names[]` 选择**多个** KB

---

## 相关文档

- [知识库 API](../api/knowledge-bases.md)
- [文档 API](../api/documents.md)
- [设计系统](design-system.md) —— 主题色板
