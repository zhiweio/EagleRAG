# 知识库模块

知识库管理 UI：`/kb` 与 `/kb/[kbName]`。组件在 `components/kb/`。

!!! note "术语"
    - **领域**（`plugin_namespace`）— API 进程部署时绑定（Milvus Database）。Core 前端不展示、也不切换领域。
    - **知识库**（`kb_name`）— 本模块创建、列表与打开的对象；领域 Milvus Database 内的标量过滤键。
    - UI 文案中 **不要** 把知识库称作「命名空间」或「租户命名空间」。

见 [多租户](../architecture/multi-tenancy.md)。

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

`KBDetailClient.tsx` —— 单个知识库深入视图。

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

`GET …/collections` —— 基础 `eagle_text` / `eagle_visual` 行数（领域插件提供时含专用 collection）。

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

重导出 / 收窄知识库模块的生成 OpenAPI 类型。

---

## 隔离 UX 说明

- URL 中 `kb_name` 为规范知识库标识（小写 + 下划线）
- 内置前端仅 Core；用户切换的是**知识库**（`kb_name`），不是部署领域
- 入库页用 `TargetKBSelector` —— 与问答 `scopeStore` 分离
- 问答 scope 抽屉可通过 `scope_filter.kb_names[]` 选择**多个** KB
- i18n：用「知识库」/ “knowledge base”；勿用「命名空间」指代 `kb_name`

---

## 相关文档

- [前端索引](index.md)
- [入库模块](ingest-module.md)
- [状态管理](state-management.md)
- [多租户](../architecture/multi-tenancy.md)
