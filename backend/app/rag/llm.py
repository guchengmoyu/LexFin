"""LLM 调用与降级（docs/05 §7）。

主渠道失败/超时 → 自动切 LLM_FALLBACK_MODEL 重试 1 次；
备用也失败 → 抛 BizError(50030)，上层返回「检索证据列表 + 提示稍后重试」。
计费与配额保护：token_usage 全量落库（由 QaService 记录）。
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List, Optional, Sequence

from loguru import logger

from app.core.config import settings
from app.core.constants import ErrorCode
from app.core.exceptions import BizError


class LLMClient:
    """OpenAI 兼容协议客户端（DeepSeek / 通义千问 / 智谱 / Kimi 可切换，ADR-03）。"""

    def __init__(self) -> None:
        self._primary = self._build(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
        self._fallback = None
        if settings.llm_fallback_enabled and settings.llm_fallback_api_key:
            self._fallback = self._build(
                settings.llm_fallback_base_url,
                settings.llm_fallback_api_key,
                settings.llm_fallback_model,
            )
        self.model_name = settings.llm_model
        self.last_usage: dict = {}
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

    @staticmethod
    def _build(base_url: str, api_key: str, model: str):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
            streaming=True,
        )

    # ---------------------------------------------------------------- 流式
    async def astream(
        self,
        messages: Sequence[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """流式产出增量文本（delta）。主渠道失败自动切备用渠道重试 1 次。"""
        last_exc: Optional[Exception] = None
        for llm, name in self._chain():
            try:
                async with self._semaphore:
                    async for chunk in self._stream_once(llm, messages, temperature, max_tokens):
                        yield chunk
                self.model_name = getattr(llm, "model_name", None) or getattr(llm, "model", name)
                return
            except Exception as exc:
                last_exc = exc
                logger.warning("LLM 渠道 {} 流式失败，尝试降级: {}", name, exc)
        raise BizError(ErrorCode.LLM_ERROR, "大模型服务暂时不可用，请稍后重试") from last_exc

    async def _stream_once(
        self, llm, messages: Sequence[dict], temperature: Optional[float], max_tokens: Optional[int]
    ) -> AsyncIterator[str]:
        kwargs: dict[str, Any] = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        async for chunk in llm.astream(list(messages), **kwargs):
            content = getattr(chunk, "content", None)
            if content:
                yield content
            usage = (getattr(chunk, "usage_metadata", None)
                     or (getattr(chunk, "response_metadata", None) or {}).get("token_usage"))
            if usage:
                self.last_usage = dict(usage)

    # ---------------------------------------------------------------- 非流式
    async def ainvoke(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """非流式调用（查询改写等轻量调用也走这里）。"""
        messages = [{"role": "user", "content": prompt}]
        last_exc: Optional[Exception] = None
        for llm, name in self._chain():
            try:
                async with self._semaphore:
                    kwargs: dict[str, Any] = {}
                    if temperature is not None:
                        kwargs["temperature"] = temperature
                    if max_tokens is not None:
                        kwargs["max_tokens"] = max_tokens
                    result = await llm.ainvoke(list(messages), **kwargs)
                self.model_name = getattr(llm, "model_name", None) or getattr(llm, "model", name)
                usage = getattr(result, "usage_metadata", None)
                if usage:
                    self.last_usage = dict(usage)
                return getattr(result, "content", "") or ""
            except Exception as exc:
                last_exc = exc
                logger.warning("LLM 渠道 {} 调用失败，尝试降级: {}", name, exc)
        raise BizError(ErrorCode.LLM_ERROR, "大模型服务暂时不可用，请稍后重试") from last_exc

    def _chain(self) -> List[tuple]:
        chain = [(self._primary, "primary")]
        if self._fallback is not None:
            chain.append((self._fallback, "fallback"))
        return chain


class FakeLLM:
    """测试/降级用确定性 LLM（docs/09 §3.2）。"""

    def __init__(self, answer: Optional[str] = None) -> None:
        self.answer = answer or "根据参考条文，该指标应当不低于100%[1]。"
        self.model_name = "fake-llm"
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def astream(self, messages, **kw) -> AsyncIterator[str]:
        for ch in self.answer:
            yield ch

    async def ainvoke(self, messages, **kw) -> str:
        return self.answer


_llm: Optional[Any] = None


def get_llm(**kwargs) -> Any:
    """装配 LLM 客户端。EMBEDDING_PROVIDER=fake 或初始化失败时降级 FakeLLM。"""
    global _llm
    if _llm is not None:
        return _llm
    try:
        _llm = LLMClient()
    except Exception as exc:  # pragma: no cover - 依赖缺失兜底
        logger.error("LLM 客户端初始化失败，降级 FakeLLM: {}", exc)
        _llm = FakeLLM()
    return _llm


def reset_llm() -> None:
    global _llm
    _llm = None
