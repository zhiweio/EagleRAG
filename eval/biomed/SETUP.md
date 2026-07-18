# SETUP：biomed 栈与 core 切换

## 原则

- **不修改** 仓库默认 `.env`（保留 core）。
- 使用 **`.env.biomed`**（gitignore）+ `docker compose --env-file .env.biomed`。
- 两套服务**不同时**运行；端口可相同。

## 创建 env

```bash
task biomed:env
# 等价：python3 eval/biomed/scripts/apply_biomed_env.py .env.biomed
```

关键覆盖：

| 变量 | 值 |
| --- | --- |
| `EAGLE_RAG_PROFILE` | `biomed` |
| `KB_NAME` | `hutchmed` |
| `VISUAL_EMBEDDING_PROVIDER` | `dashscope` |
| `VISUAL_EMBEDDING_MODEL` | `qwen3-vl-embedding` |
| `EAGLE_BIOMED_ENCODER_MODE` | `auto` |
| `EAGLE_BIOMED_ALLOW_DETERMINISTIC` | `0` |

模板见仓库根目录 [`.env.biomed.example`](../../.env.biomed.example)。

## Core 视觉 = DashScope（强制）

- **不要**把 biomed 测试栈设为 `VISUAL_EMBEDDING_PROVIDER=pixelrag`。
- 切图仍可能使用 `pixelrag_render`；**嵌入**走百炼 `qwen3-vl-embedding`。
- 需有效 `DASHSCOPE_API_KEY`（与 text embed / rerank 共用）。
- Biomed 专用编码器（PubMedBERT / ChemBERTa / BiomedCLIP）与 Core `eagle_visual` 正交。

## 依赖

```bash
uv sync --extra biomed   # open-clip / BiomedCLIP 路径
```

## 大陆网络：语料下载代理

拉取 Europe PMC / PubChem / FDA 等外网资料若卡住，使用本地 HTTP 代理：

```bash
export BIOMED_HTTP_PROXY=http://127.0.0.1:1087
export BIOMED_SSL_INSECURE=1   # 本地代理 MITM 导致证书校验失败时
task biomed:corpus
# 或 task biomed:corpus CORPUS_ARGS='--local-proxy --insecure-ssl'
```

详见 [CORPUS.md](./CORPUS.md)。

## 启停

```bash
task down                # 停 core（如在跑）
task biomed:up
task biomed:health       # 断言 default_namespace=biomed
task biomed:down         # 结束后
# 恢复 core：docker compose --env-file .env --profile dev up -d
```

## 健康检查要点

```bash
curl -s localhost:8000/health/plugins | jq .
# default_namespace == "biomed"
# enabled 含 plugins.biomed
```
