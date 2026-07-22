"""
LLM Tool — 大模型调用封装
支持 OpenAI 兼容接口（DeepSeek / Qwen / GPT 等）
"""

import asyncio
from typing import Optional, AsyncGenerator

from openai import AsyncOpenAI

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger("tool.llm")
settings = get_settings()


class LLMTool:
    """LLM 对话工具（异步，支持重试 + 流式）"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.llm.openai_api_key,
            base_url=settings.llm.openai_base_url,
            timeout=settings.llm.openai_timeout,
            max_retries=0,  # 我们自己控制重试
        )
        self.model = settings.llm.openai_model_chat
        self.default_temperature = settings.llm.openai_temperature
        self.default_max_tokens = settings.llm.openai_max_tokens
        self.retry_delays = settings.llm.retry_delays_list

    async def chat(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """
        同步对话（返回完整文本）

        Args:
            messages: OpenAI 格式消息列表 [{"role": "system/user/assistant", "content": "..."}]
            temperature: 温度参数，默认使用配置值
            max_tokens: 最大 token 数，默认使用配置值
            model: 模型名称，默认使用配置值
        Returns:
            LLM 回复文本
        """
        response = await self.chat_with_retry(
            messages=messages,
            temperature=temperature or self.default_temperature,
            max_tokens=max_tokens or self.default_max_tokens,
            model=model or self.model,
        )
        return response

    async def chat_with_retry(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: str = None,
    ) -> str:
        """带指数退避重试的对话调用"""
        model = model or self.model
        last_error = None

        for attempt, delay in enumerate([0] + self.retry_delays):
            if delay > 0:
                logger.info(f"LLM 重试等待 {delay}s（第 {attempt} 次重试）")
                await asyncio.sleep(delay)

            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                usage = response.usage
                if usage:
                    logger.info(
                        f"LLM 调用成功 | model={model} | "
                        f"prompt_tokens={usage.prompt_tokens} | "
                        f"completion_tokens={usage.completion_tokens}"
                    )
                return content.strip()

            except Exception as e:
                last_error = e
                logger.warning(f"LLM 调用失败（第 {attempt + 1} 次）: {e}")

        logger.error(f"LLM 调用最终失败，已重试 {len(self.retry_delays) + 1} 次: {last_error}")
        raise last_error

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式对话（SSE 用）

        Yields:
            逐块文本内容
        """
        model = model or self.model
        temperature = temperature or self.default_temperature
        max_tokens = max_tokens or self.default_max_tokens

        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            raise

    async def classify(self, prompt: str, temperature: float = 0.1) -> str:
        """
        分类任务专用（低温度，短输出）

        Args:
            prompt: 完整的分类 Prompt
            temperature: 温度（默认 0.1，要求确定性输出）
        Returns:
            分类结果文本
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages=messages, temperature=temperature, max_tokens=64)


# 全局单例
_llm_tool: Optional[LLMTool] = None


def get_llm_tool() -> LLMTool:
    """获取 LLM 工具单例"""
    global _llm_tool
    if _llm_tool is None:
        _llm_tool = LLMTool()
    return _llm_tool
