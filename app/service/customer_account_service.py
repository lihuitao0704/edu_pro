"""Customer self-service answers backed by owner-scoped database queries.

This service deliberately accepts only the authenticated customer id.  It is
the boundary that prevents a natural-language customer query from reaching
the unrestricted NL2SQL or internal risk-monitoring capabilities.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.entities import (
    FinCustomerProfile,
    FinHoldings,
    FinProduct,
    FinRiskAlert,
    FinTransaction,
    SysUser,
)


class CustomerAccountService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def answer(
        self,
        message: str,
        *,
        customer_id: int,
        intent: str,
        entities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entities = entities or {}
        if intent == "customer_transaction_guidance":
            return self._transaction_guidance(message, entities)
        if intent == "customer_risk_explanation":
            return await self._risk_explanation(customer_id)
        if intent == "customer_recommendation_explanation":
            return await self._recommendation_explanation(customer_id)

        if any(word in message for word in ("持仓", "仓位")):
            return await self._holdings(customer_id)
        if any(word in message for word in ("交易记录", "交易流水", "流水", "最近交易")):
            return await self._transactions(customer_id)
        if any(word in message for word in ("余额", "可用资金", "账户资金")):
            return await self._balance(customer_id)
        if any(word in message for word in ("风险", "风评", "风险等级")):
            return await self._risk_profile(customer_id)
        return await self._account_summary(customer_id)

    async def _account_summary(self, customer_id: int) -> dict[str, Any]:
        user = await self.db.get(SysUser, customer_id)
        profile = await self._profile(customer_id)
        if user is None:
            return self._not_found()
        level = profile.risk_level_name if profile and profile.risk_level_name else "尚未评定"
        balance = self._money(user.balance)
        return {
            "reply": (
                f"您好，{user.real_name or '客户'}。您的当前风险等级为 **{level}**，"
                f"账户可用余额为 **¥{balance}**。\n\n"
                "您还可以继续问我：“查看我的持仓”“查询我的交易记录”"
                "或“为什么我的产品范围受到限制”。"
            ),
            "data": {
                "customer_id": customer_id,
                "risk_level": level,
                "balance": float(user.balance or 0),
                "scope": "self",
            },
        }

    async def _balance(self, customer_id: int) -> dict[str, Any]:
        user = await self.db.get(SysUser, customer_id)
        if user is None:
            return self._not_found()
        return {
            "reply": (
                f"您的账户当前可用余额为 **¥{self._money(user.balance)}**。"
                "\n\n余额仅供查询，具体可投资金额还需结合在途交易和产品起购要求确认。"
            ),
            "data": {
                "customer_id": customer_id,
                "balance": float(user.balance or 0),
                "scope": "self",
            },
        }

    async def _risk_profile(self, customer_id: int) -> dict[str, Any]:
        profile = await self._profile(customer_id)
        if profile is None:
            return {
                "reply": (
                    "您目前还没有可用的风险评估结果。为了让推荐更合适，"
                    "请先完成风险测评；如刚完成测评，可稍后刷新再试。"
                ),
                "data": {"customer_id": customer_id, "scope": "self"},
            }
        level = profile.risk_level_name or "尚未评定"
        score = (
            f"，综合评分 {profile.risk_score}"
            if profile.risk_score is not None
            else ""
        )
        notice = (
            "\n\n您的账户目前有风险关注事项，部分产品或交易可能暂时受到限制。"
            "您可以继续问我“为什么受到限制”。"
            if profile.risk_flag in ("warning", "high")
            else "\n\n当前未发现需要特别提示的账户风险状态。"
        )
        return {
            "reply": f"您的当前风险等级为 **{level}**{score}。{notice}",
            "data": {
                "customer_id": customer_id,
                "risk_level": level,
                "risk_score": profile.risk_score,
                "has_risk_notice": profile.risk_flag in ("warning", "high"),
                "scope": "self",
            },
        }

    async def _holdings(self, customer_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            select(FinHoldings, FinProduct)
            .join(FinProduct, FinProduct.id == FinHoldings.product_id)
            .where(FinHoldings.customer_id == customer_id)
            .order_by(FinHoldings.current_value.desc())
            .limit(20)
        )
        rows = result.all()
        if not rows:
            return {
                "reply": "您当前没有查询到持仓记录。如刚完成交易，持仓信息可能需要稍后更新。",
                "data": {
                    "customer_id": customer_id,
                    "holdings": [],
                    "scope": "self",
                },
            }
        total = sum(Decimal(str(holding.current_value or 0)) for holding, _ in rows)
        lines = [
            "| 产品 | 风险等级 | 当前市值 | 浮动盈亏 |",
            "|---|:---:|---:|---:|",
        ]
        items = []
        for holding, product in rows:
            lines.append(
                f"| {product.product_name} | {product.risk_level or '-'} | "
                f"¥{self._money(holding.current_value)} | "
                f"¥{self._money(holding.profit_loss)} |"
            )
            items.append(
                {
                    "product_id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "risk_level": product.risk_level,
                    "current_value": float(holding.current_value or 0),
                    "profit_loss": float(holding.profit_loss or 0),
                }
            )
        return {
            "reply": (
                f"以下是您的当前持仓，共 **{len(items)}** 项，总市值约 "
                f"**¥{self._money(total)}**：\n\n" + "\n".join(lines)
            ),
            "data": {
                "customer_id": customer_id,
                "holdings": items,
                "total_value": float(total),
                "scope": "self",
            },
        }

    async def _transactions(self, customer_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            select(FinTransaction, FinProduct)
            .join(FinProduct, FinProduct.id == FinTransaction.product_id)
            .where(FinTransaction.customer_id == customer_id)
            .order_by(FinTransaction.create_time.desc())
            .limit(10)
        )
        rows = result.all()
        if not rows:
            return {
                "reply": "您当前没有查询到交易记录。",
                "data": {
                    "customer_id": customer_id,
                    "transactions": [],
                    "scope": "self",
                },
            }
        type_names = {"purchase": "申购", "redeem": "赎回", "transfer": "转账"}
        lines = [
            "| 时间 | 类型 | 产品 | 金额 | 状态 |",
            "|---|:---:|---|---:|:---:|",
        ]
        items = []
        for transaction, product in rows:
            created = (
                transaction.create_time.strftime("%Y-%m-%d")
                if transaction.create_time
                else "-"
            )
            transaction_type = type_names.get(
                transaction.transaction_type, transaction.transaction_type
            )
            lines.append(
                f"| {created} | {transaction_type} | {product.product_name} | "
                f"¥{self._money(transaction.amount)} | {transaction.status or '-'} |"
            )
            items.append(
                {
                    "transaction_no": transaction.transaction_no,
                    "type": transaction.transaction_type,
                    "product_name": product.product_name,
                    "amount": float(transaction.amount or 0),
                    "status": transaction.status,
                    "create_time": transaction.create_time.isoformat()
                    if transaction.create_time
                    else None,
                }
            )
        return {
            "reply": "以下是您最近的交易记录：\n\n" + "\n".join(lines),
            "data": {
                "customer_id": customer_id,
                "transactions": items,
                "scope": "self",
            },
        }

    async def _risk_explanation(self, customer_id: int) -> dict[str, Any]:
        profile = await self._profile(customer_id)
        result = await self.db.execute(
            select(FinRiskAlert)
            .where(
                FinRiskAlert.customer_id == customer_id,
                FinRiskAlert.status.in_(("pending", "processing")),
            )
            .order_by(FinRiskAlert.create_time.desc())
            .limit(5)
        )
        alerts = list(result.scalars())
        if not alerts and (profile is None or profile.risk_flag not in ("warning", "high")):
            return {
                "reply": (
                    "目前没有查询到未处理的账户风险提示。产品可购买范围仍会受到"
                    "您的风险等级、产品适当性和起购条件影响。"
                ),
                "data": {
                    "customer_id": customer_id,
                    "active_alert_count": 0,
                    "scope": "self",
                },
            }

        level_names = {"high": "较高", "medium": "中等", "low": "一般"}
        type_names = {
            "concentration": "持仓集中度",
            "large_transaction": "大额交易",
            "frequent_transaction": "交易频率",
            "suitability": "产品适当性",
        }
        highest = alerts[0].alert_level if alerts else (profile.risk_flag or "warning")
        categories = sorted(
            {
                type_names.get(alert.alert_type, "账户交易")
                for alert in alerts
            }
        )
        category_text = "、".join(categories) if categories else "账户风险"
        return {
            "reply": (
                f"您的账户当前有 **{len(alerts) or 1} 项待关注提示**，"
                f"主要与 **{category_text}** 有关，关注程度为"
                f" **{level_names.get(highest, '需关注')}**。\n\n"
                "这可能使部分高风险产品或大额交易暂时受到限制。为保护您的账户，"
                "助手不会展示内部规则明细，也不会直接解除预警。您可以在业务页面"
                "提交人工复核，或联系平台客服核实处理进度。"
            ),
            "data": {
                "customer_id": customer_id,
                "active_alert_count": len(alerts) or 1,
                "alert_level": highest,
                "categories": categories,
                "scope": "self",
            },
        }

    async def _recommendation_explanation(
        self, customer_id: int
    ) -> dict[str, Any]:
        profile = await self._profile(customer_id)
        result = await self.db.execute(
            select(FinRiskAlert.id).where(
                FinRiskAlert.customer_id == customer_id,
                FinRiskAlert.status.in_(("pending", "processing")),
            )
        )
        active_alert_count = len(result.scalars().all())
        risk_limit = active_alert_count > 0 or (
            profile is not None and profile.risk_flag in ("warning", "high")
        )
        constraint = (
            "您的账户当前有待关注事项，候选范围暂时收窄到 R1-R2；"
            if risk_limit
            else "候选产品需要符合您的风险等级；"
        )
        return {
            "reply": (
                f"本次只展示一款，并不代表平台只有这一款产品。{constraint}"
                "系统还会继续校验产品是否在售、产品类型与风险等级是否一致、"
                "收益数据是否合理，以及起购金额和期限等条件。经过这些筛选后，"
                "当前只有这一款满足全部条件。\n\n"
                "您可以补充期望期限或产品类型，我会按新条件重新筛选；"
                "如果想了解账户限制，也可以问我“为什么只能买 R2 产品”。"
            ),
            "data": {
                "customer_id": customer_id,
                "active_alert_count": active_alert_count,
                "risk_limited": risk_limit,
                "scope": "self",
            },
        }

    @staticmethod
    def _transaction_guidance(
        message: str, entities: dict[str, Any]
    ) -> dict[str, Any]:
        operation = "购买"
        if "赎回" in message:
            operation = "赎回"
        elif any(word in message for word in ("转账", "转出", "汇款")):
            operation = "转账"
        elif "开户" in message:
            operation = "开户"

        amount = entities.get("amount")
        product = entities.get("product_name")
        recognized = []
        if product:
            recognized.append(f"产品：{product}")
        if amount:
            recognized.append(f"金额：¥{float(amount):,.2f}")
        detail = f"\n\n已识别：{'；'.join(recognized)}。" if recognized else ""

        if operation == "购买" and not product:
            reply = (
                "可以，我先帮您选到合适的产品，再进入购买确认。"
                "请告诉我投资金额、期望期限和风险偏好；"
                "您也可以直接说“我有50万，希望稳健配置3年”。"
            )
        else:
            reply = (
                f"我已理解您想办理{operation}。AI 助手可以帮助核对条件和整理参数，"
                "但不会在聊天中直接提交资金操作。请在交易页面核对产品、金额、费用"
                "和风险提示后，由您本人确认；如账户存在风险限制，页面会提示人工复核。"
                f"{detail}"
            )
        return {
            "reply": reply,
            "data": {
                "operation": operation,
                "draft": {
                    "product_name": product,
                    "amount": amount,
                },
                "requires_user_confirmation": True,
                "scope": "self",
            },
        }

    async def _profile(self, customer_id: int) -> FinCustomerProfile | None:
        result = await self.db.execute(
            select(FinCustomerProfile).where(
                FinCustomerProfile.customer_id == customer_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _money(value: Decimal | int | float | None) -> str:
        return f"{Decimal(str(value or 0)):,.2f}"

    @staticmethod
    def _not_found() -> dict[str, Any]:
        return {
            "reply": "暂时没有查询到您的账户资料，请刷新后重试或联系平台客服核实。",
            "data": {"scope": "self"},
        }
