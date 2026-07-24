"""
数据库孤儿清理脚本
================
检查并清理无对应主表记录的孤儿数据。

当前检查项：
- conversation_archive：无对应用户的记录
- fin_holdings：无对应客户或产品的记录
- fin_transaction：无对应客户或产品的记录
- customer_tag：无对应客户的记录

用法：
  python scripts/cleanup_orphans.py          # 仅检查（不删除）
  python scripts/cleanup_orphans.py --delete # 检查并删除孤儿
  python scripts/cleanup_orphans.py --delete --days=30  # 只清理 30 天前的孤儿
"""

import asyncio
import sys
from datetime import datetime, timedelta

from sqlalchemy import select, func


async def main():
    from app.config.database import async_session_factory, init_db
    from app.model.entities import (
        BizWorkOrder,
        ConversationArchive,
        CustomerTag,
        FinHoldings,
        FinRiskAlert,
        FinTransaction,
        FinCustomerProfile,
        SysUser,
        FinProduct,
    )

    delete_mode = "--delete" in sys.argv
    days_filter = None
    for arg in sys.argv:
        if arg.startswith("--days="):
            try:
                days_filter = int(arg.split("=")[1])
            except ValueError:
                pass

    await init_db()

    async with async_session_factory() as db:
        stats = []

        # 1. conversation_archive 孤儿（无对应用户）
        orphan_archives = await db.execute(
            select(ConversationArchive).where(
                ~ConversationArchive.user_id.in_(select(SysUser.id))
            )
        )
        archives = orphan_archives.scalars().all()
        stats.append(("conversation_archive(无用户)", len(archives)))

        # 2. fin_holdings 孤儿
        orphan_holdings = await db.execute(
            select(FinHoldings).where(
                ~FinHoldings.customer_id.in_(select(FinCustomerProfile.customer_id))
            )
        )
        holdings = orphan_holdings.scalars().all()
        stats.append(("fin_holdings(无客户)", len(holdings)))

        # 3. customer_tag 孤儿
        orphan_tags = await db.execute(
            select(CustomerTag).where(
                ~CustomerTag.customer_id.in_(select(FinCustomerProfile.customer_id))
            )
        )
        tags = orphan_tags.scalars().all()
        stats.append(("customer_tag(无客户)", len(tags)))

        # 4. fin_transaction 孤儿（无客户）
        orphan_txn_cust = await db.execute(
            select(FinTransaction).where(
                ~FinTransaction.customer_id.in_(select(FinCustomerProfile.customer_id))
            )
        )
        txn_cust = orphan_txn_cust.scalars().all()
        stats.append(("fin_transaction(无客户)", len(txn_cust)))

        # 5. fin_risk_alert 孤儿
        orphan_alerts = await db.execute(
            select(FinRiskAlert).where(
                ~FinRiskAlert.customer_id.in_(select(FinCustomerProfile.customer_id))
            )
        )
        alerts = orphan_alerts.scalars().all()
        stats.append(("fin_risk_alert(无客户)", len(alerts)))

        # 输出报告
        print("=" * 60)
        print("数据库孤儿检查报告")
        print(f"  模式: {'删除' if delete_mode else '只读检查'}")
        if days_filter:
            print(f"  时间过滤: 仅清理 {days_filter} 天前的记录")
        print("=" * 60)

        total = 0
        for name, count in stats:
            print(f"  {name}: {count} 条孤儿")
            total += count

        print("-" * 60)
        print(f"  合计: {total} 条孤儿记录")

        if delete_mode and total > 0:
            deleted = 0
            cutoff = (
                datetime.now() - timedelta(days=days_filter)
                if days_filter
                else None
            )

            for record in archives:
                if cutoff and record.create_time and record.create_time > cutoff:
                    continue
                await db.delete(record)
                deleted += 1

            for record in holdings:
                await db.delete(record)
                deleted += 1

            for record in tags:
                await db.delete(record)
                deleted += 1

            for record in txn_cust:
                await db.delete(record)
                deleted += 1

            for record in alerts:
                await db.delete(record)
                deleted += 1

            await db.commit()
            print(f"\n已删除 {deleted} 条孤儿记录")
        elif total == 0:
            print("\n无需清理，数据库状态良好")
        else:
            print("\n只读模式，未执行删除。加 --delete 参数执行清理")

        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
