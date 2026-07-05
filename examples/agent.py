"""Eagle-RAG MCP 客户端示例（stdio + streamable HTTP 双模式）。

提供两种 MCP 客户端形态：

1. **stdio 模式**（``MCP_MODE=stdio``，默认）：LlamaIndex ``FunctionAgent`` +
   ``llama-index-tools-mcp`` ``BasicMCPClient``，子进程拉起本地 MCP server
   （``python -m eagle_rag.api.mcp_server``，stdio transport），无需 HTTP/鉴权，
   适合本地开发与单机 Agent。LLM 自主选择调用 ``ingest`` / ``query`` /
   ``retrieve_text`` / ``retrieve_visual`` 四项工具，编排一次多模态问答闭环。

2. **HTTP 模式**（``MCP_MODE=http``）：``PrefectHQ/fastmcp`` ``Client`` +
   streamable HTTP transport，经 HTTPS + ``Authorization: Bearer <api_key>``
   连接云端 MCP 服务（如 Docker Swarm + HAProxy 部署的
   ``https://eagle-rag.example.com/mcp``），适合远程 / 多租户 / 云端 Agent。
   直接调用四项工具并打印结果，展示远程连接与鉴权用法。

环境变量：
- ``MCP_MODE``：``stdio``（默认）或 ``http``，选择客户端形态。
- ``MCP_URL``：HTTP 模式的 MCP 端点 URL（如 ``https://eagle-rag.example.com/mcp``）。
- ``MCP_API_KEY``：HTTP 模式的 Bearer API Key（与 server ``AUTH_API_KEY`` 一致）。
- ``LLM_API_KEY`` / ``LLM_BASE_URL`` / ``LLM_MODEL``：stdio 模式下 LLM 配置
  （经 ``settings.yaml`` 占位符展开，详见 ``eagle_rag/config.py``）。

运行方式：
1. stdio 模式（本地）：
   .. code-block:: bash

       python examples/agent.py
       # 或：MCP_MODE=stdio python examples/agent.py

   前置：启动后端依赖（Milvus / Redis / PostgreSQL / MinIO / Celery worker / VLM），
   配置好 ``settings.llm``（api_key / base_url / model）。

2. HTTP 模式（远程）：
   .. code-block:: bash

       MCP_MODE=http \\
       MCP_URL=https://eagle-rag.example.com/mcp \\
       MCP_API_KEY=<your-api-key> \\
       python examples/agent.py

   前置：MCP server 已部署（Docker Swarm + HAProxy），且 ``AUTH_ENABLED=true``。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# 示例入库样本路径（占位）。用户可替换为真实政策文档路径；不存在时 ingest 工具会
# 通过 graceful degradation 返回 error，不阻塞后续问答。
_SAMPLE_PATH = "data/samples/policy_sample.pdf"


# ---------------------------------------------------------------------------
# stdio 模式：LlamaIndex FunctionAgent + BasicMCPClient（本地子进程）
# ---------------------------------------------------------------------------


def _build_llm() -> Any:
    """从 settings.llm 构造 DashScope LLM（api_key / base_url / model 均来自配置）。"""
    from llama_index.llms.dashscope import DashScope

    from eagle_rag.config import get_settings

    cfg = get_settings().llm
    return DashScope(model=cfg.model, api_key=cfg.api_key, api_base=cfg.base_url)


def _extract_text(resp: object) -> str:
    """从 Agent.run 返回值中提取文本（兼容 response / content / str 多种形态）。"""
    for attr in ("response", "content", "output"):
        val = getattr(resp, attr, None)
        if isinstance(val, str) and val:
            return val
    return str(resp)


async def main_stdio() -> None:
    """stdio 模式主流程：子进程拉起 MCP server → 拉取工具 → 构造 Agent → 问答闭环。"""
    from llama_index.core.agent import FunctionAgent
    from llama_index.tools.mcp import BasicMCPClient, McpToolSpec

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 1. 连接 MCP server（子进程 stdio transport）。
    # 用当前 Python 解释器以模块方式拉起，保证环境与依赖一致。
    # BasicMCPClient 会 fork 子进程，经 stdin/stdout 走 MCP stdio transport。
    client = BasicMCPClient(sys.executable, args=["-m", "eagle_rag.api.mcp_server"])

    # 2. 拉取工具清单。注意：在 async 环境必须用 to_tool_list_async()，
    #    同步版 to_tool_list() 会抛 "cannot be called from a running event loop"。
    tool_spec = McpToolSpec(client=client)
    tools = await tool_spec.to_tool_list_async()
    logger.info(
        "从 MCP server 拉取到 %d 个工具: %s",
        len(tools),
        [t.metadata.name for t in tools],
    )
    if not tools:
        logger.error("未拉取到任何 MCP 工具，请确认 eagle_rag.api.mcp_server 可正常启动")
        return

    # 3. 构造 FunctionAgent（工具由 LLM 自主选择调用）。
    llm = _build_llm()
    agent = FunctionAgent.from_tools(tools, llm=llm)

    # 4. 示例对话：先入库一份政策样本，再问个税问题。
    ingest_prompt = (
        f"请调用 ingest 工具入库一份政策文档，source_uri 用 {_SAMPLE_PATH}，"
        f"source_type 用 policy。如果文件不存在或入库失败，请直接说明原因，"
        f"然后继续回答下一个问题。"
    )
    question = "个人所得税法第三条的适用范围是什么？请基于知识库中的政策文档作答，并列出来源。"

    # 入库步骤（容错：失败仅打印，不中断后续问答）。
    print("\n===== 步骤 1：入库政策样本 =====")
    try:
        resp1 = await agent.run(ingest_prompt)
        print(_extract_text(resp1))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ingest 步骤失败（不阻塞后续问答）: %s", exc)

    # 问答步骤。
    print("\n===== 步骤 2：多模态问答 =====")
    try:
        resp2 = await agent.run(question)
        print(_extract_text(resp2))
    except Exception as exc:  # noqa: BLE001
        logger.error("问答步骤失败: %s", exc)
        raise


# ---------------------------------------------------------------------------
# HTTP 模式：fastmcp Client + streamable HTTP（远程云端）
# ---------------------------------------------------------------------------


async def main_http() -> None:
    """HTTP 模式主流程：fastmcp Client 连接云端 MCP → 调用工具 → 打印结果。

    示范远程 Agent 如何经 HTTPS + Bearer API Key 调用云端 MCP 服务的四项工具。
    不依赖 LlamaIndex（直接调工具，不经 LLM 编排），聚焦传输与鉴权用法。
    """
    from fastmcp import Client

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    url = os.environ.get("MCP_URL", "http://localhost:8081/")
    api_key = os.environ.get("MCP_API_KEY", "")

    if not api_key:
        logger.warning(
            "MCP_API_KEY 未设置；若 server AUTH_ENABLED=true 将返回 401。"
            "本地开发 AUTH_ENABLED=false 时可省略。"
        )

    # fastmcp Client 支持 HTTP transport：传 URL 即可识别为 streamable HTTP。
    # 鉴权经自定义 headers 注入 ``Authorization: Bearer <api_key>``，
    # 由 server 端 ``StaticTokenVerifier`` 校验（见 configure_mcp_auth）。
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with Client(url, headers=headers) as client:
        # 1. 列出工具（验证连接与鉴权通过）。
        tools = await client.list_tools()
        print(f"\n===== MCP 工具清单（{len(tools)} 个）=====")
        for t in tools:
            print(f"  - {t.name}: {t.description.splitlines()[0] if t.description else ''}")

        # 2. 调用 retrieve_text 检索（最能验证端到端链路，无副作用）。
        print("\n===== 调用 retrieve_text =====")
        try:
            result = await client.call_tool(
                "retrieve_text",
                {"query": "个人所得税法第三条", "top_k": 3},
            )
            # fastmcp Client 返回 CallToolResult，其 .data 为结构化结果。
            payload = result.data if hasattr(result, "data") else result.structured_content
            if isinstance(payload, list):
                print(f"检索到 {len(payload)} 个文本切片：")
                for i, item in enumerate(payload, 1):
                    if isinstance(item, dict) and "error" in item:
                        print(f"  [{i}] error: {item['error']}")
                    else:
                        score = item.get("score") if isinstance(item, dict) else None
                        text = (item.get("text", "") if isinstance(item, dict) else str(item))[:120]
                        print(f"  [{i}] score={score} text={text!r}...")
            else:
                print(f"结果: {payload}")
        except Exception as exc:  # noqa: BLE001
            logger.error("retrieve_text 调用失败: %s", exc)

        # 3. 调用 query 问答（含生成，耗时较长）。
        print("\n===== 调用 query =====")
        try:
            result = await client.call_tool(
                "query",
                {"query": "个人所得税法第三条的适用范围是什么？"},
            )
            payload = result.data if hasattr(result, "data") else result.structured_content
            if isinstance(payload, dict):
                if "error" in payload:
                    print(f"error: {payload['error']}")
                else:
                    answer = payload.get("answer", "")
                    route = payload.get("route", "")
                    print(f"route: {route}")
                    print(f"answer: {answer}")
            else:
                print(f"结果: {payload}")
        except Exception as exc:  # noqa: BLE001
            logger.error("query 调用失败: %s", exc)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def main() -> None:
    """按 ``MCP_MODE`` 环境变量分发到 stdio / HTTP 模式。"""
    mode = os.environ.get("MCP_MODE", "stdio").lower()
    if mode == "http":
        await main_http()
    else:
        await main_stdio()


if __name__ == "__main__":
    asyncio.run(main())
