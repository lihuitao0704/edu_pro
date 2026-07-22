"""记忆单元校验器（MemoryUnitValidator）— 六维属性校验"""


class MemoryUnitValidator:
    VALID_RISK_LEVELS = ["C1", "C2", "C3", "C4", "C5"]
    VALID_ALERT_LEVELS = ["low", "medium", "high"]
    VALID_STATUSES = ["pending", "processing", "resolved", "false_positive"]
    VALID_SOURCES = ["风评问卷", "AI对话提取", "用户自述", "行为推断", "系统默认"]

    def validate(self, unit: dict) -> dict:
        errors = []
        if unit.get("risk_level") and unit["risk_level"] not in self.VALID_RISK_LEVELS:
            errors.append(f"无效风险等级: {unit['risk_level']}")
        if unit.get("alert_level") and unit["alert_level"] not in self.VALID_ALERT_LEVELS:
            errors.append(f"无效预警级别: {unit['alert_level']}")
        if unit.get("status") and unit["status"] not in self.VALID_STATUSES:
            errors.append(f"无效状态: {unit['status']}")
        if unit.get("risk_score") is not None and not (0 <= unit["risk_score"] <= 100):
            errors.append(f"风险评分超出范围: {unit['risk_score']}")
        if unit.get("confidence_score") is not None and not (0.0 <= unit["confidence_score"] <= 1.0):
            errors.append(f"置信度超出范围: {unit['confidence_score']}")
        if unit.get("create_time") and unit.get("update_time"):
            if unit["update_time"] < unit["create_time"]:
                errors.append("更新时间早于创建时间")
        if unit.get("source", "") and unit["source"] not in self.VALID_SOURCES:
            errors.append(f"无效来源: {unit['source']}")
        if "customer_id" not in unit:
            errors.append("缺少必填字段: customer_id")
        return {"valid": len(errors) == 0, "errors": errors}
