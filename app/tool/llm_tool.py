"""
LLM Tool — 大模型调用封装
支持 OpenAI 兼容接口（DeepSeek / Qwen / GPT 等）
"""

import asyncio
import httpx
from typing import Optional, AsyncGenerator

from openai import AsyncOpenAI

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger("tool.llm")
settings = get_settings()


class LLMTool:
    """LLM 对话工具（异步，支持重试 + 流式）"""

    def __init__(self):
        # 创建自定义 httpx 客户端，禁用自动代理检测（trust_env=False）
        # 避免系统代理配置导致连接失败
        http_client = httpx.AsyncClient(
            trust_env=False,  # 禁用自动代理检测
            timeout=settings.llm.openai_timeout,
        )

        self.client = AsyncOpenAI(
            api_key=settings.llm.openai_api_key,
            base_url=settings.llm.openai_base_url,
            timeout=settings.llm.openai_timeout,
            max_retries=0,  # 我们自己控制重试
            http_client=http_client,  # 使用自定义客户端
        )
        self.model = settings.llm.openai_model_chat
        self.default_temperature = settings.llm.openai_temperature
        self.default_max_tokens = settings.llm.openai_max_tokens
        self.retry_delays = settings.llm.retry_delays_list

        # 启动时打印配置信息（帮助诊断）
        api_key_masked = settings.llm.openai_api_key[:6] + "***" if settings.llm.openai_api_key else "(空)"
        logger.info(f"LLMTool 初始化 | base_url={settings.llm.openai_base_url} | model={self.model}")
        logger.info(f"LLMTool 初始化 | api_key={api_key_masked}")
        logger.info(f"LLMTool 初始化 | 已禁用自动代理检测 (trust_env=False)")

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

                # 调试：打印原始响应类型和内容
                logger.info(f"LLM 原始响应类型: {type(response).__name__}")

                # 检查 response 类型（某些情况下可能返回字符串）
                if isinstance(response, str):
                    logger.warning(f"LLM 返回字符串而非对象，可能是 API 错误: {response[:500]}")
                    last_error = Exception(f"API 返回字符串: {response[:200]}")
                    continue

                # 检查 response 是否有 choices 属性
                if not hasattr(response, 'choices'):
                    logger.warning(f"LLM 响应缺少 choices 属性 | 类型: {type(response)} | 内容: {str(response)[:500]}")
                    last_error = Exception(f"响应格式异常: {type(response)}")
                    continue

                choice = response.choices[0] if response.choices else None
                message = choice.message if choice else None

                # 优先取 content，如果为空则尝试 reasoning_content（推理模型兼容）
                content = ""
                if message:
                    content = getattr(message, "content", None) or ""
                    # 推理模型（如 deepseek-r1）可能把结果放在 reasoning_content
                    if not content.strip():
                        reasoning = getattr(message, "reasoning_content", None) or ""
                        if reasoning.strip():
                            logger.info(f"LLM 使用 reasoning_content（推理模型模式）| model={model}")
                            content = reasoning

                usage = response.usage
                if usage:
                    logger.info(
                        f"LLM 调用成功 | model={model} | "
                        f"prompt_tokens={usage.prompt_tokens} | "
                        f"completion_tokens={usage.completion_tokens}"
                    )

                if not content.strip():
                    logger.warning(f"LLM 返回空内容 | model={model} | message={message}")

                return content.strip()

            except Exception as e:
                last_error = e
                # 打印完整错误信息（包括异常类型和属性）
                error_detail = f"{type(e).__name__}: {str(e)}"
                if hasattr(e, 'status_code'):
                    error_detail += f" | status_code={e.status_code}"
                if hasattr(e, 'request'):
                    error_detail += f" | request_url={e.request.url if hasattr(e.request, 'url') else 'N/A'}"
                logger.warning(f"LLM 调用失败（第 {attempt + 1} 次）: {error_detail}")

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

    async def classify(self, prompt: str, temperature: float = 0.1, max_tokens: int = 64) -> str:
        """
        分类任务专用（低温度，短输出）

        Args:
            prompt: 完整的分类 Prompt
            temperature: 温度（默认 0.1，要求确定性输出）
            max_tokens: 最大输出 token 数（默认 64，JSON 分类建议 256+）
        Returns:
            分类结果文本
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)

    async def chat_with_fallback(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        带多级降级的对话调用（P0-14 修复）。

        降级链：主模型 → 本地 LongCat 备用 → 兜底话术
        每一级独立配置 timeout，失败自动切换到下一级。

        Args:
            messages: OpenAI 格式消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
        Returns:
            LLM 回复文本，全部失败时返回兜底话术
        """
        temp = temperature or self.default_temperature
        tokens = max_tokens or self.default_max_tokens

        # ── 第1级：主模型（当前配置的模型） ──
        try:
            return await asyncio.wait_for(
                self.chat(messages=messages, temperature=temp, max_tokens=tokens),
                timeout=self.client.timeout if self.client.timeout else 30,
            )
        except Exception as e:
            logger.warning(f"主模型({self.model})调用失败，尝试降级: {type(e).__name__}")

        # ── 第2级：LongCat 备用模型 ──
        if settings.llm.longcat_api_key and settings.llm.longcat_model != self.model:
            try:
                logger.info(f"降级到 LongCat 备用模型: {settings.llm.longcat_model}")
                fallback_client = AsyncOpenAI(
                    api_key=settings.llm.longcat_api_key,
                    base_url=settings.llm.longcat_base_url,
                    timeout=20,
                    max_retries=0,
                )
                response = await asyncio.wait_for(
                    fallback_client.chat.completions.create(
                        model=settings.llm.longcat_model,
                        messages=messages,
                        temperature=temp,
                        max_tokens=tokens,
                    ),
                    timeout=20,
                )
                content = response.choices[0].message.content or ""
                logger.info(f"LongCat 降级成功 | model={settings.llm.longcat_model}")
                return content.strip()
            except Exception as e2:
                logger.warning(f"LongCat 降级失败: {type(e2).__name__}")

        # ── 第3级：兜底话术 ──
        logger.error(f"所有 LLM 调用均失败，返回兜底话术")
        return (
            "抱歉，系统当前繁忙，暂时无法为您提供完整服务。"
            "建议您稍后重试，或拨打客服热线400-XXX-XXXX咨询人工客服。"
            "我们正在努力恢复服务，感谢您的耐心等待。"
        )


# 全局单例
_llm_tool: Optional[LLMTool] = None


def get_llm_tool() -> LLMTool:
    """获取 LLM 工具单例"""
    global _llm_tool
    if _llm_tool is None:
        _llm_tool = LLMTool()
    return _llm_tool
