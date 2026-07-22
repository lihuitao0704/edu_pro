"""自定义异常类"""


class AppException(Exception):
    """应用基础异常"""
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


class ProfileNotFound(AppException):
    """画像不存在"""
    def __init__(self, customer_id: int):
        super().__init__(f"客户 {customer_id} 的画像不存在", code=404)


class RiskAssessmentExpired(AppException):
    """风险评估已过期"""
    def __init__(self, customer_id: int):
        super().__init__(f"客户 {customer_id} 的风险评估已过期，请重新评估", code=403)


class SuitabilityMismatch(AppException):
    """适当性不匹配"""
    def __init__(self, customer_level: str, product_level: str):
        super().__init__(
            f"适当性不匹配：客户等级 {customer_level} 不允许购买 {product_level} 等级产品",
            code=403,
        )


class CircuitBreakerTriggered(AppException):
    """熔断规则触发"""
    def __init__(self, rule_id: str, reason: str):
        super().__init__(f"熔断规则 {rule_id} 触发：{reason}", code=403)


class ConfidenceTooLow(AppException):
    """置信度过低"""
    def __init__(self, label_name: str, confidence: float):
        super().__init__(f"标签 '{label_name}' 置信度过低 ({confidence:.2f})，不可用于决策", code=422)
