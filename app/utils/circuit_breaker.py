"""
熔断器工具类 — 防止级联故障

提供简单的熔断器实现，用于保护可能失败的外部服务调用（如 Neo4j、Redis、LLM API 等）

状态机：
  CLOSED（正常）→ 连续失败 N 次 → OPEN（熔断）
  OPEN → 等待超时时间 → HALF_OPEN（尝试恢复）
  HALF_OPEN → 成功 → CLOSED
  HALF_OPEN → 失败 → OPEN

使用示例：
    breaker = CircuitBreaker(fail_max=5, reset_timeout=60)

    async def risky_operation():
        # 可能抛出异常的操作
        pass

    try:
        await breaker.call(risky_operation)
    except CircuitBreakerError:
        # 熔断器打开，快速失败
        return fallback_response
"""

import time
from enum import Enum
from typing import Callable, Any


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"          # 正常状态
    OPEN = "open"              # 熔断状态（快速失败）
    HALF_OPEN = "half_open"    # 半开状态（尝试恢复）


class CircuitBreakerError(Exception):
    """熔断器异常：熔断器打开时抛出"""
    pass


class CircuitBreaker:
    """
    简单熔断器实现

    参数：
        fail_max: 最大失败次数，达到后触发熔断（默认5次）
        reset_timeout: 熔断后等待恢复的秒数（默认60秒）
    """

    def __init__(self, fail_max: int = 5, reset_timeout: int = 60):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.fail_count = 0
        self.last_fail_time = None
        self.state = CircuitState.CLOSED

    def is_open(self) -> bool:
        """检查熔断器是否打开"""
        if self.state == CircuitState.OPEN:
            # 检查是否应该尝试恢复（进入半开状态）
            if self.last_fail_time and (time.time() - self.last_fail_time > self.reset_timeout):
                self.state = CircuitState.HALF_OPEN
                return False
            return True
        return False

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        使用熔断器保护函数调用

        参数：
            func: 要保护的异步函数
            *args, **kwargs: 函数参数
        返回：
            函数执行结果
        抛出：
            CircuitBreakerError: 熔断器打开时抛出
            Exception: 函数执行失败时抛出
        """
        # 检查熔断器状态
        if self.is_open():
            raise CircuitBreakerError("熔断器打开，服务暂时不可用")

        try:
            # 执行函数
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """成功回调：重置状态"""
        self.fail_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self):
        """失败回调：累计失败次数，达到阈值时熔断"""
        self.fail_count += 1
        self.last_fail_time = time.time()

        if self.fail_count >= self.fail_max:
            self.state = CircuitState.OPEN

    def reset(self):
        """手动重置熔断器"""
        self.fail_count = 0
        self.last_fail_time = None
        self.state = CircuitState.CLOSED
