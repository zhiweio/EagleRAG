"""Multimodal generation engine (Phase 5.2).

Extends LlamaIndex ``CustomQueryEngine`` and processes the routed ``NodeWithScore``
list as follows:

1. **Split**: partition nodes into ``TextNode`` (text) and ``ImageNode`` (image).
2. **Rerank**: text path prefers ``DashScopeRerank`` (Qwen qwen3-rerank); falls back
   to descending score when unavailable. Image path has no visual reranker and falls
   back to descending score. Each path keeps ``top_n`` nodes.
3. **Build VLM input**: assemble a prompt from reference text + image captions +
   query + language constraint, and convert accessible image nodes into
   ``ImageDocument`` (unreadable ones are skipped).
4. **Call VLM**: ``DashScopeMultiModal`` (Qwen-VL-Max) via
   ``complete(prompt=..., image_documents=[...])``; on failure returns
   ``"生成失败：{error}"`` without raising.
5. **Build sources/steps**: sources carry text type/path/level and image
   image_id/image_path/page/position; steps expose the route→recall→rerank→generate
   chain for frontend traceability.

Both VLM and reranker are constructed lazily: when ``DashScopeMultiModal`` /
``DashScopeRerank`` optional deps are missing they fall back to ``None`` (a missing
VLM yields a failure message at generation; a missing reranker falls back to score
sorting), so the module imports and supports mock injection under minimal deps.
"""

from __future__ import annotations

import base64
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from llama_index.core.bridge.pydantic import Field
from llama_index.core.query_engine import CustomQueryEngine
from llama_index.core.schema import ImageDocument, ImageNode, NodeWithScore, TextNode
from opentelemetry.trace import StatusCode

from eagle_rag.config import get_settings
from eagle_rag.telemetry import (
    get_ai_logger,
    get_logger,
    set_llm_span_attributes,
    trace_span,
    truncate,
)

__all__ = ["EagleMultimodalQueryEngine"]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)

# CJK ideograph range, used for language detection.
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def _image_message_payload(doc: ImageDocument) -> dict[str, str] | None:
    """Build a DashScope multimodal ``{"image": ...}`` content item from a document."""
    raw = getattr(doc, "image", None)
    if isinstance(raw, bytes):
        b64 = base64.b64encode(raw).decode()
        return {"image": f"data:image/png;base64,{b64}"}
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.startswith("data:"):
            return {"image": text}
        # ``ImageDocument(image=bytes)`` stores raw base64 without a data-URI prefix.
        mime = "image/jpeg" if text.startswith("/9j/") else "image/png"
        return {"image": f"data:{mime};base64,{text}"}
    url = getattr(doc, "image_url", None)
    if url:
        return {"image": str(url)}
    path = getattr(doc, "image_path", None)
    if path:
        return {"image": str(path)}
    return None


def _as_int_list(value: Any) -> list[int]:
    """Coerce an arbitrary iterable into a list of ints, dropping non-numeric items."""
    out: list[int] = []
    for item in value or []:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _as_str_list(value: Any) -> list[str]:
    """Coerce an arbitrary iterable into a list of non-empty trimmed strings."""
    return [str(item) for item in (value or []) if item is not None and str(item).strip()]


def _extract_message_text(content: Any) -> str:
    """Normalize DashScope multimodal ``message.content`` to plain text.

    Non-streaming responses use ``[{"text": "..."}]``; streaming chunks use a
    plain ``str`` (see DashScope ``MultiModalConversation`` streaming examples).
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif isinstance(item, str) and item:
                parts.append(item)
        return "".join(parts)
    return str(content)


def _stream_text_delta(full: str, piece: str, *, incremental: bool) -> tuple[str, str]:
    """Derive ``(new_full, delta)`` from one streaming chunk."""
    if not piece:
        return full, ""
    if incremental:
        if piece.startswith(full):
            return piece, piece[len(full) :]
        return piece, piece
    new_full = full + piece
    return new_full, piece


# ---------------------------------------------------------------------------
# Lazy default construction (falls back to None when optional deps are missing)
# ---------------------------------------------------------------------------


@dataclass
class _VLMResponse:
    """Lightweight response object mimicking llama-index CompletionResponse."""

    text: str = ""
    delta: str = ""
    usage: Any = None


@dataclass
class _DashScopeVLM:
    """Thin wrapper around the native ``dashscope.MultiModalConversation`` SDK.

    The deprecated ``llama-index-multi-modal-llms-dashscope`` package constructs
    ``ChatMessage(content=[{"text": ...}])`` with raw dicts, which the new
    llama-index core (>=0.12) rejects. This wrapper bypasses the llama-index
    ChatMessage layer entirely and calls the DashScope multi-modal API directly,
    preserving the ``complete(prompt, image_documents)`` /
    ``stream_complete(prompt, image_documents)`` interface used by the engine.
    """

    model_name: str = ""
    api_key: str = ""

    def _build_messages(
        self, prompt: str, image_documents: list[ImageDocument] | None
    ) -> list[dict]:
        content: list[dict] = []
        for doc in image_documents or []:
            item = _image_message_payload(doc)
            if item is not None:
                content.append(item)
        content.append({"text": prompt})
        return [{"role": "user", "content": content}]

    def complete(
        self, prompt: str, image_documents: list[ImageDocument] | None = None
    ) -> _VLMResponse:
        from dashscope import MultiModalConversation  # type: ignore

        messages = self._build_messages(prompt, image_documents)
        resp = MultiModalConversation.call(
            model=self.model_name,
            messages=messages,
            api_key=self.api_key,
        )
        text = ""
        usage = None
        try:
            if getattr(resp, "status_code", 0) == 200:
                text = _extract_message_text(resp.output.choices[0].message.content)
                usage = getattr(resp, "usage", None)
            else:
                text = f"生成失败：{getattr(resp, 'message', resp)}"
        except Exception:  # noqa: BLE001
            text = f"生成失败：{resp}"
        return _VLMResponse(text=text, usage=usage)

    def stream_complete(
        self, prompt: str, image_documents: list[ImageDocument] | None = None
    ) -> Iterator[_VLMResponse]:
        from dashscope import MultiModalConversation  # type: ignore

        messages = self._build_messages(prompt, image_documents)
        incremental = True
        responses = MultiModalConversation.call(
            model=self.model_name,
            messages=messages,
            api_key=self.api_key,
            stream=True,
            incremental_output=incremental,
        )
        full = ""
        for r in responses:
            if getattr(r, "status_code", 0) == 200:
                try:
                    piece = _extract_message_text(r.output.choices[0].message.content)
                except Exception:  # noqa: BLE001
                    piece = ""
                full, delta = _stream_text_delta(full, piece, incremental=incremental)
                if delta:
                    yield _VLMResponse(text=full, delta=delta, usage=getattr(r, "usage", None))
            else:
                err = f"生成失败：{getattr(r, 'message', r)}"
                yield _VLMResponse(text=err, delta=err)
                return


def _default_multi_modal_llm() -> Any:
    """Lazily build a native DashScope multi-modal wrapper (Qwen-VL) from ``settings.vlm``.

    Returns ``None`` when the ``dashscope`` SDK is missing. An empty ``api_key``
    does not raise here (it is only required at call time).
    """
    try:
        import dashscope  # type: ignore  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        logger.debug("DashScope SDK unavailable; multimodal LLM will be None: %s", exc)
        return None
    try:
        vlm_cfg = get_settings().vlm
        return _DashScopeVLM(model_name=vlm_cfg.model, api_key=vlm_cfg.api_key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("DashScope VLM construction failed: %s", exc)
        return None


def _default_text_reranker() -> Any:
    """Lazily build the text reranker (``DashScopeRerank``, Qwen qwen3-rerank).

    Returns ``None`` when the integration package is missing.
    """
    try:
        from llama_index.postprocessor.dashscope_rerank import DashScopeRerank  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.debug("DashScopeRerank unavailable; text reranker will be None: %s", exc)
        return None
    try:
        rerank_cfg = get_settings().rerank.text
        return DashScopeRerank(model=rerank_cfg.model, api_key=rerank_cfg.api_key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("DashScopeRerank construction failed: %s", exc)
        return None


def _default_image_reranker() -> Any:
    """No image reranker is wired up yet; returns ``None``."""
    return None


def _is_attachment_node(nws: NodeWithScore) -> bool:
    return (nws.node.metadata or {}).get("source") == "attachment"


def _extract_usage(resp: Any) -> tuple[int | None, int | None]:
    """Extract prompt_tokens/completion_tokens from an LLM response.

    Returns ``(None, None)`` when usage is absent.
    """
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None, None
    if isinstance(usage, dict):
        return usage.get("prompt_tokens"), usage.get("completion_tokens")
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )


# ---------------------------------------------------------------------------
# EagleMultimodalQueryEngine
# ---------------------------------------------------------------------------


class EagleMultimodalQueryEngine(CustomQueryEngine):
    """Multimodal QA engine: split → rerank → VLM generate → build sources/steps."""

    # ``Any`` accepts Mock / MultiModalLLM / BaseNodePostprocessor and similar types.
    multi_modal_llm: Any = Field(default=None)
    text_reranker: Any = Field(default=None)
    image_reranker: Any = Field(default=None)
    top_n: int = Field(default=3)

    def __init__(
        self,
        *,
        multi_modal_llm: Any = None,
        text_reranker: Any = None,
        image_reranker: Any = None,
        top_n: int = 3,
        **kwargs: Any,
    ) -> None:
        vlm = multi_modal_llm
        if vlm is None:
            vlm = _default_multi_modal_llm()
        tr = text_reranker
        if tr is None:
            tr = _default_text_reranker()
        ir = image_reranker
        if ir is None:
            ir = _default_image_reranker()
        super().__init__(
            multi_modal_llm=vlm,
            text_reranker=tr,
            image_reranker=ir,
            top_n=top_n,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # CustomQueryEngine abstract method implementations
    # ------------------------------------------------------------------

    def custom_query(
        self,
        query_str: str,
        *,
        nodes: list[NodeWithScore] | None = None,
        route_info: dict | None = None,
        language: str | None = None,
        attachment_image_docs: list[ImageDocument] | None = None,
        attach_parse_step: dict[str, Any] | None = None,
        attachment_ids: list[str] | None = None,
    ) -> dict:
        """Run split → rerank → VLM generate → build sources/steps."""
        _ = attachment_ids  # kept for backward compatibility with callers
        prepared = self._prepare_generation(
            query_str,
            nodes=nodes,
            route_info=route_info,
            language=language,
            attachment_image_docs=attachment_image_docs,
            attach_parse_step=attach_parse_step,
        )
        answer = self._invoke_vlm(prepared["prompt"], prepared["image_docs"])
        return self._finalize_result(prepared, answer)

    def stream_custom_query(
        self,
        query_str: str,
        *,
        nodes: list[NodeWithScore] | None = None,
        route_info: dict | None = None,
        language: str | None = None,
        attachment_image_docs: list[ImageDocument] | None = None,
        attach_parse_step: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream generation, yielding step/sources/token/done events."""
        prepared = self._prepare_generation(
            query_str,
            nodes=nodes,
            route_info=route_info,
            language=language,
            attachment_image_docs=attachment_image_docs,
            attach_parse_step=attach_parse_step,
        )
        yield {
            "event": "step",
            "data": {
                "name": "rerank",
                "text_top": [self._node_path(n) for n in prepared["top_text"]],
                "visual_top": [self._node_image_id(n) for n in prepared["top_image"]],
                "text_kept": len(prepared["top_text"]),
                "visual_kept": len(prepared["top_image"]),
            },
        }
        yield {"event": "sources", "data": prepared["sources"]}

        answer_parts: list[str] = []
        for delta in self._invoke_vlm_stream(prepared["prompt"], prepared["image_docs"]):
            answer_parts.append(delta)
            yield {"event": "token", "data": {"delta": delta}}

        answer = "".join(answer_parts)
        result = self._finalize_result(prepared, answer)
        yield {
            "event": "done",
            "data": {
                "answer": result["answer"],
                "sources": result["sources"],
                "route": result["route"],
                "steps": result["steps"],
            },
        }

    def _prepare_generation(
        self,
        query_str: str,
        *,
        nodes: list[NodeWithScore] | None,
        route_info: dict | None,
        language: str | None,
        attachment_image_docs: list[ImageDocument] | None,
        attach_parse_step: dict[str, Any] | None,
    ) -> dict[str, Any]:
        nodes = nodes or []
        route_info = (
            dict(route_info)
            if route_info
            else {"mode": "auto", "selected": [], "reason": "no route info provided"}
        )

        text_nodes = [
            n for n in nodes if isinstance(n.node, TextNode) and not isinstance(n.node, ImageNode)
        ]
        image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
        orig_text_count = len(text_nodes)
        orig_image_count = len(image_nodes)

        top_text = self._rerank(text_nodes, self.text_reranker, query_str, self.top_n)
        top_image = self._rerank(image_nodes, self.image_reranker, query_str, self.top_n)

        if language is None:
            language = self._detect_language(query_str)

        kb_text = [n for n in top_text if not _is_attachment_node(n)]
        attach_text = [n for n in top_text if _is_attachment_node(n)]

        prompt = self._build_prompt(query_str, kb_text, attach_text, top_image, language)
        image_docs = self._nodes_to_image_documents(top_image)
        if attachment_image_docs:
            image_docs.extend(attachment_image_docs)

        text_sources = self.text_sources_from_nodes(top_text)
        image_sources = [self._image_source(n) for n in top_image]
        sources = {"text": text_sources, "image": image_sources}

        steps: list[dict[str, Any]] = [
            {
                "name": "route",
                "mode": route_info.get("mode"),
                "selected": route_info.get("selected", []),
                "reason": route_info.get("reason"),
            },
            {
                "name": "recall",
                "text_count": orig_text_count,
                "visual_count": orig_image_count,
            },
        ]
        if attach_parse_step:
            steps.append(attach_parse_step)
        steps.extend(
            [
                {
                    "name": "rerank",
                    "text_top": [self._node_path(n) for n in top_text],
                    "visual_top": [self._node_image_id(n) for n in top_image],
                    "text_kept": len(top_text),
                    "visual_kept": len(top_image),
                },
                {
                    "name": "generate",
                    "model": get_settings().vlm.model,
                    "language": language,
                    "image_docs_count": len(image_docs),
                },
            ]
        )

        return {
            "prompt": prompt,
            "image_docs": image_docs,
            "sources": sources,
            "route": route_info,
            "steps": steps,
            "top_text": top_text,
            "top_image": top_image,
        }

    @staticmethod
    def _finalize_result(prepared: dict[str, Any], answer: str) -> dict[str, Any]:
        return {
            "answer": answer,
            "sources": prepared["sources"],
            "route": prepared["route"],
            "steps": prepared["steps"],
        }

    # ------------------------------------------------------------------
    # Helpers: rerank / language / prompt / ImageDocument / sources
    # ------------------------------------------------------------------

    @staticmethod
    def _rerank(
        nodes: list[NodeWithScore],
        reranker: Any,
        query_str: str,
        top_n: int,
    ) -> list[NodeWithScore]:
        """Rerank one node path.

        Uses ``postprocess_nodes`` when a reranker is available, otherwise falls
        back to descending score. Returns the top ``top_n`` nodes.
        """
        if not nodes:
            return []
        stage = "visual" if isinstance(nodes[0].node, ImageNode) else "text"
        t0 = time.monotonic()
        with trace_span("rerank"):
            processed = nodes
            if reranker is not None:
                try:
                    processed = reranker.postprocess_nodes(nodes, query_str=query_str)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("reranker call failed; falling back to score ordering: %s", exc)
                    processed = nodes
            # Sort by score descending (also applies reranker's new scores; treat None as 0).
            processed = sorted(
                processed,
                key=lambda nws: nws.score if nws.score is not None else 0.0,
                reverse=True,
            )
            result = processed[:top_n]
            try:
                key = "image_id" if stage == "visual" else "path"
                top_list = [
                    truncate(str((nws.node.metadata or {}).get(key) or ""), 128) for nws in result
                ]
                ai_logger.info(
                    "rerank",
                    stage=stage,
                    kept=len(result),
                    top=top_list,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)
            return result

    @staticmethod
    def _detect_language(text: str) -> str:
        """Return ``zh`` if the text contains CJK characters, otherwise ``en``."""
        return "zh" if _CJK_PATTERN.search(text or "") else "en"

    @staticmethod
    def _build_prompt(
        query: str,
        kb_text_nodes: list[NodeWithScore],
        attach_text_nodes: list[NodeWithScore],
        image_nodes: list[NodeWithScore],
        language: str,
    ) -> str:
        """Assemble the prompt.

        Combines reference text + user attachments + image captions + query +
        language constraint.
        """
        parts: list[str] = [
            "你是多模态问答助手，请基于以下参考信息回答用户问题。",
            "",
        ]

        parts.append("【参考文本】")
        if kb_text_nodes:
            for idx, nws in enumerate(kb_text_nodes, start=1):
                meta = nws.node.metadata or {}
                path = meta.get("path", "")
                content = (nws.node.text or "").strip()
                parts.append(f"[{idx}] 路径: {path}")
                parts.append(content)
        else:
            parts.append("（无）")

        parts.append("")
        parts.append("【用户附件】")
        if attach_text_nodes:
            for idx, nws in enumerate(attach_text_nodes, start=1):
                meta = nws.node.metadata or {}
                file_name = meta.get("file_name") or meta.get("path") or ""
                content = (nws.node.text or "").strip()
                parts.append(f"[{idx}] 文件: {file_name}")
                parts.append(content)
        else:
            parts.append("（无）")

        parts.append("")
        parts.append("【参考图片】")
        if image_nodes:
            for idx, nws in enumerate(image_nodes, start=1):
                meta = nws.node.metadata or {}
                image_id = meta.get("image_id", "")
                page = meta.get("page", "")
                position = meta.get("position", "")
                parent_section = meta.get("parent_section", "")
                content_summary = meta.get("content_summary", "")
                parts.append(
                    f"[{idx}] image_id={image_id}, 页码={page}, 位置={position}, "
                    f"章节={parent_section}, 摘要={content_summary}"
                )
        else:
            parts.append("（无）")

        parts.append("")
        parts.append("【用户问题】")
        parts.append(query)
        parts.append("")
        parts.append(
            "图片已作为多模态输入提供。回答时勿使用 Markdown 图片语法或虚构 URL；"
            "描述图示内容即可，引用参考文本请用 [n] 编号。"
        )
        lang_label = "中文" if language == "zh" else "English"
        parts.append(f"请用{lang_label}回答。")
        return "\n".join(parts)

    @staticmethod
    def _nodes_to_image_documents(image_nodes: list[NodeWithScore]) -> list[ImageDocument]:
        """Convert each ``ImageNode`` into an ``ImageDocument`` for the VLM.

        Tries ``image_path`` / ``image_url`` first. When LlamaIndex rejects
        MinIO presigned URLs (not publicly reachable), falls back to loading raw
        bytes via ``images.store.get_image_bytes`` using ``metadata.image_id``.
        """
        from eagle_rag.images.store import get_image_bytes

        docs: list[ImageDocument] = []
        for nws in image_nodes:
            node = nws.node
            meta = node.metadata or {}
            image_path = getattr(node, "image_path", None)
            image_url = getattr(node, "image_url", None)
            doc: ImageDocument | None = None
            for candidate in (image_path, image_url):
                if not candidate:
                    continue
                try:
                    doc = ImageDocument(image_path=candidate)
                    break
                except Exception:  # noqa: BLE001
                    try:
                        doc = ImageDocument(image_url=candidate)
                        break
                    except Exception:  # noqa: BLE001
                        doc = None
            if doc is None:
                image_id = meta.get("image_id")
                if image_id:
                    try:
                        doc = ImageDocument(image=get_image_bytes(image_id))
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "ImageDocument bytes fallback failed image_id=%s: %s",
                            image_id,
                            exc,
                        )
                        doc = None
            if doc is not None:
                docs.append(doc)
        return docs

    def _invoke_vlm(self, prompt: str, image_docs: list[ImageDocument]) -> str:
        """Call the VLM ``complete``; on failure return a failure message without raising."""
        vlm = self.multi_modal_llm
        if vlm is None:
            return "生成失败：未配置多模态大模型"
        model = get_settings().vlm.model
        t0 = time.monotonic()
        with trace_span("generate") as span:
            set_llm_span_attributes(
                span, system="dashscope", model=model, prompt=prompt, completion=""
            )
            try:
                resp = vlm.complete(prompt=prompt, image_documents=image_docs)
                answer = getattr(resp, "text", str(resp))
                set_llm_span_attributes(
                    span, system="dashscope", model=model, prompt=prompt, completion=answer
                )
                prompt_tokens, completion_tokens = _extract_usage(resp)
                if prompt_tokens is not None or completion_tokens is not None:
                    set_llm_span_attributes(
                        span,
                        system="dashscope",
                        model=model,
                        prompt=prompt,
                        completion=answer,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                try:
                    ai_logger.info(
                        "generate",
                        model=model,
                        prompt=truncate(prompt, 512),
                        completion=truncate(answer, 1024),
                        image_docs_count=len(image_docs),
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        language=self._detect_language(prompt),
                        status="ok",
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("telemetry emit failed", exc_info=True)
                return answer
            except Exception as exc:  # noqa: BLE001
                logger.warning("VLM generation failed: %s", exc)
                if span:
                    span.set_status(StatusCode.ERROR)
                    span.record_exception(exc)
                try:
                    ai_logger.info(
                        "generate",
                        model=model,
                        prompt=truncate(prompt, 512),
                        completion="",
                        image_docs_count=len(image_docs),
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        error=truncate(str(exc), 256),
                        status="failed",
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("telemetry emit failed", exc_info=True)
                return f"生成失败：{exc}"

    def _invoke_vlm_stream(self, prompt: str, image_docs: list[ImageDocument]) -> Iterator[str]:
        """Stream the VLM; falls back to a single ``complete`` call when unavailable."""
        vlm = self.multi_modal_llm
        if vlm is None:
            yield "生成失败：未配置多模态大模型"
            return
        model = get_settings().vlm.model
        if hasattr(vlm, "stream_complete"):
            t0 = time.monotonic()
            with trace_span("generate") as span:
                set_llm_span_attributes(
                    span, system="dashscope", model=model, prompt=prompt, completion=""
                )
                try:
                    stream = vlm.stream_complete(prompt=prompt, image_documents=image_docs)
                    answer_parts: list[str] = []
                    for chunk in stream:
                        delta = getattr(chunk, "delta", None) or getattr(chunk, "text", None)
                        if delta:
                            answer_parts.append(str(delta))
                            yield str(delta)
                    if not answer_parts:
                        logger.warning("VLM stream returned no tokens; falling back to complete()")
                        raise RuntimeError("empty VLM stream")
                    answer = "".join(answer_parts)
                    set_llm_span_attributes(
                        span, system="dashscope", model=model, prompt=prompt, completion=answer
                    )
                    try:
                        ai_logger.info(
                            "generate",
                            model=model,
                            prompt=truncate(prompt, 512),
                            completion=truncate(answer, 1024),
                            image_docs_count=len(image_docs),
                            latency_ms=int((time.monotonic() - t0) * 1000),
                            language=self._detect_language(prompt),
                            status="ok",
                            stream=True,
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug("telemetry emit failed", exc_info=True)
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("VLM streaming failed; falling back to complete(): %s", exc)
                    if span:
                        span.set_status(StatusCode.ERROR)
                        span.record_exception(exc)
        yield self._invoke_vlm(prompt, image_docs)

    @staticmethod
    def _text_source(nws: NodeWithScore) -> dict:
        """Map a text ``NodeWithScore`` to a client source.

        Surfaces the full chunk body (``content``) and its semantic metadata so
        the UI can render retrieved evidence, not just a reference. ``content`` is
        capped at ``router.source_content_max_chars`` to bound payload size.
        """
        meta = nws.node.metadata or {}
        content = nws.node.get_content() if hasattr(nws.node, "get_content") else ""
        content = content or getattr(nws.node, "text", "") or ""
        cap = getattr(get_settings().router, "source_content_max_chars", 4000)
        if cap and len(content) > cap:
            content = content[:cap]
        src: dict[str, Any] = {
            "type": meta.get("type", "text"),
            "path": meta.get("path"),
            "level": meta.get("level"),
            "document_id": meta.get("document_id"),
            "score": nws.score,
            "content": content or None,
            "summary": meta.get("summary") or None,
            "keywords": _as_str_list(meta.get("keywords")),
            "page_nums": _as_int_list(meta.get("page_nums")),
            "file_path": meta.get("file_path") or None,
            "document_top_summary": meta.get("document_top_summary") or None,
            "kb_name": meta.get("kb_name"),
            "source_type": meta.get("source_type"),
        }
        chunk_count = meta.get("chunk_count")
        if isinstance(chunk_count, int):
            src["chunk_count"] = chunk_count
        if meta.get("source") == "attachment":
            src["source"] = "attachment"
            src["attachment_id"] = meta.get("attachment_id")
            src["file_name"] = meta.get("file_name")
        elif meta.get("file_name"):
            src["file_name"] = meta.get("file_name")
            src["document_name"] = meta.get("document_name") or meta.get("file_name")
        return src

    @staticmethod
    def _enrich_text_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Join document registry names for KB chunks missing ``file_name``."""
        missing_ids = [
            str(src["document_id"])
            for src in sources
            if src.get("document_id") and not src.get("file_name")
        ]
        if not missing_ids:
            return sources
        plugin_namespace: str | None = None
        try:
            from eagle_rag.plugins import get_plugin_manager

            plugin_namespace = get_plugin_manager().default_namespace
        except Exception:  # noqa: BLE001
            plugin_namespace = None
        try:
            from eagle_rag.index.registry import lookup_documents_sync

            docs = lookup_documents_sync(missing_ids, plugin_namespace=plugin_namespace)
        except Exception:  # noqa: BLE001
            return sources
        for src in sources:
            doc_id = src.get("document_id")
            if not doc_id or src.get("file_name"):
                continue
            doc = docs.get(str(doc_id))
            if not doc:
                continue
            name = doc.get("name")
            if name:
                src["file_name"] = name
                src["document_name"] = name
        return sources

    @staticmethod
    def text_sources_from_nodes(nodes: list[NodeWithScore]) -> list[dict[str, Any]]:
        """Map text nodes to API sources with registry-backed ``file_name``."""
        sources = [EagleMultimodalQueryEngine._text_source(n) for n in nodes]
        return EagleMultimodalQueryEngine._enrich_text_sources(sources)

    @staticmethod
    def _image_source(nws: NodeWithScore) -> dict:
        """Map a visual ``NodeWithScore`` to a client source.

        Carries the four semantic-tree anchor fields so the tile can be placed
        back onto the document's parsed structure by the UI.
        """
        meta = nws.node.metadata or {}
        year = meta.get("year")
        src: dict[str, Any] = {
            "type": "image",
            "image_id": meta.get("image_id"),
            "image_path": meta.get("image_path") or getattr(nws.node, "image_path", None),
            "page": meta.get("page"),
            "position": meta.get("position"),
            "document_id": meta.get("document_id"),
            "score": nws.score,
            "chunk_type": meta.get("chunk_type"),
            "parent_section": meta.get("parent_section"),
            "content_summary": meta.get("content_summary"),
            "source_chunk_id": meta.get("source_chunk_id"),
            "kb_name": meta.get("kb_name"),
            "source_type": meta.get("source_type"),
            "year": year if isinstance(year, int) else None,
        }
        if meta.get("source") == "attachment":
            src["source"] = "attachment"
            src["attachment_id"] = meta.get("attachment_id")
            src["file_name"] = meta.get("file_name")
        return src

    @staticmethod
    def _node_path(nws: NodeWithScore) -> Any:
        return (nws.node.metadata or {}).get("path")

    @staticmethod
    def _node_image_id(nws: NodeWithScore) -> Any:
        return (nws.node.metadata or {}).get("image_id")
