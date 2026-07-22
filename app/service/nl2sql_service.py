"""
NL2SQL 数据分析服务 — 自然语言 → SQL → 执行 → 解读
"""

from app.config.database import SessionLocal
from app.tool.llm_client import LLMClient
from app.model import entities
from sqlalchemy import text
from typing import List, Dict, Optional, Tuple
import re
import logging

logger = logging.getLogger(__name__)

# 全部 10 张业务表（sys_table_dict 是内部管理表，不暴露）
ALL_TABLES = [
    "sys_user",
    "fin_product",
    "fin_customer_profile",
    "fin_transaction",
    "fin_holdings",
    "fin_risk_assessment",
    "fin_risk_alert",
    "biz_work_order",
    "conversation_archive",
    "fin_knowledge_meta",
]


class NL2SQLService:
    """自然语言转 SQL 服务"""

    def __init__(self):
        self.llm: LLMClient = LLMClient()
        self.table_map: Dict[str, str] = {
            "用户": "sys_user",
            "客户": "sys_user",
            "员工": "sys_user",
            "产品": "fin_product",
            "理财": "fin_product",
            "持仓": "fin_holdings",
            "持有": "fin_holdings",
            "份额": "fin_holdings",
            "交易": "fin_transaction",
            "申购": "fin_transaction",
            "赎回": "fin_transaction",
            "流水": "fin_transaction",
            "画像": "fin_customer_profile",
            "风险": "fin_risk_alert",
            "预警": "fin_risk_alert",
            "风控": "fin_risk_alert",
            "工单": "biz_work_order",
            "知识": "fin_knowledge_meta",
        }
        self._schema_cache: Optional[str] = None
        logger.info("NL2SQLService 初始化完成")

    def _get_all_schemas(self) -> str:
        """获取所有表的 CREATE TABLE 语句文本（带缓存）"""
        if self._schema_cache is not None:
            return self._schema_cache

        logger.info("从数据库加载所有表的 Schema …")
        db = SessionLocal()
        try:
            schema_parts: List[str] = []
            for table_name in ALL_TABLES:
                sql = text(
                    "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT "
                    "FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name "
                    "ORDER BY ORDINAL_POSITION"
                )
                result = db.execute(sql, {"table_name": table_name})
                rows = result.fetchall()

                if not rows:
                    logger.warning(f"表 {table_name} 不存在或没有字段，跳过")
                    continue

                cols: List[str] = []
                for row in rows:
                    col_name = row[0]
                    col_type = row[1]
                    nullable = "NULL" if row[2] == "YES" else "NOT NULL"
                    default = f" DEFAULT {row[3]}" if row[3] else ""
                    comment = f" COMMENT '{row[4]}'" if row[4] else ""
                    cols.append(
                        f"  `{col_name}` {col_type} {nullable}{default}{comment}"
                    )

                ddl = f"CREATE TABLE `{table_name}` (\n" + ",\n".join(cols) + "\n);"
                schema_parts.append(ddl)

            self._schema_cache = "\n\n".join(schema_parts)
            logger.info(f"已加载 {len(schema_parts)} 张表的 Schema")
            return self._schema_cache
        finally:
            db.close()

    def _get_dynamic_schema(self, query: str) -> str:
        """根据用户问题动态提取相关表的 Schema"""
        related_tables: set = set()
        for keyword, table_name in self.table_map.items():
            if keyword in query:
                related_tables.add(table_name)

        if not related_tables:
            related_tables = {"sys_user", "fin_product", "fin_holdings"}
            logger.info(f"未匹配到关键词，使用默认表: {related_tables}")

        full_schema = self._get_all_schemas()
        parts: List[str] = []
        for table_name in related_tables:
            pattern = rf"CREATE TABLE `{table_name}`[\s\S]*?;"
            match = re.search(pattern, full_schema)
            if match:
                parts.append(match.group())

        logger.info(f"动态匹配到 {len(parts)} 张相关表: {related_tables}")
        return "\n\n".join(parts) if parts else full_schema

    @staticmethod
    def _get_few_shot_examples() -> str:
        """返回 Few-shot 示例"""
        return """
【示例】
用户问：查询所有在售产品
SQL：SELECT * FROM `fin_product` WHERE `status` = '在售'

用户问：客户张三的持仓有哪些
SQL：SELECT h.* FROM `fin_holdings` h JOIN `sys_user` u ON h.`customer_id` = u.`id` WHERE u.`real_name` = '张三'

用户问：统计各产品类型的平均收益率
SQL：SELECT `product_type`, AVG(`expected_return`) FROM `fin_product` GROUP BY `product_type`

用户问：查询客户张三的画像
SQL：SELECT * FROM `fin_customer_profile` WHERE `customer_id` = (SELECT `id` FROM `sys_user` WHERE `real_name` = '张三')

用户问：AUM超过100万的客户有多少个
SQL：SELECT COUNT(*) FROM `fin_customer_profile` WHERE `total_assets` > 1000000
"""

    def generate_sql(self, query: str) -> str:
        """根据自然语言生成 SQL"""
        logger.info(f"生成 SQL，用户查询: {query}")
        schema = self._get_dynamic_schema(query)
        examples = self._get_few_shot_examples()
        full_schema = schema + "\n" + examples
        sql = self.llm.generate_sql(query, full_schema)
        logger.info(f"生成 SQL: {sql}")
        return sql

    @staticmethod
    def validate_sql(sql: str) -> Tuple[bool, str]:
        """SQL 安全校验"""
        if not sql or not sql.strip():
            logger.warning("SQL 为空")
            return False, "SQL 语句为空"

        sql_upper = sql.upper().strip()

        if not sql_upper.startswith("SELECT"):
            logger.warning(f"SQL 非 SELECT 语句: {sql[:50]}...")
            return False, "只允许 SELECT 查询"

        forbidden = [
            "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
            "TRUNCATE", "CREATE", "EXEC", "EXECUTE",
        ]
        for keyword in forbidden:
            if re.search(rf"\b{keyword}\b", sql_upper):
                logger.warning(f"SQL 包含禁止关键词: {keyword}")
                return False, f"禁止执行危险操作: {keyword}"

        logger.info("SQL 校验通过")
        return True, ""

    @staticmethod
    def execute_sql(sql: str) -> Dict:
        """执行 SQL 返回结果（最多 100 行）"""
        logger.info(f"执行 SQL: {sql[:100]}...")
        db = SessionLocal()
        try:
            result = db.execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchall()
            rows = rows[:100]
            data: List[Dict] = [dict(zip(columns, row)) for row in rows]
            logger.info(f"查询返回 {len(data)} 行")
            return {"columns": columns, "rows": data, "row_count": len(data)}
        except Exception as e:
            logger.error(f"SQL 执行失败: {e}")
            return {"error": str(e)}
        finally:
            db.close()

    def query_and_explain(self, query: str) -> Dict:
        """完整流程：生成 SQL → 校验 → 执行 → 解读"""
        logger.info(f"===== NL2SQL 完整流程开始 =====")
        logger.info(f"用户问题: {query}")

        try:
            sql = self.generate_sql(query)

            valid, msg = self.validate_sql(sql)
            if not valid:
                return {
                    "success": False,
                    "sql": sql,
                    "query_result": None,
                    "explanation": None,
                    "error": msg,
                }

            result = self.execute_sql(sql)
            if "error" in result:
                return {
                    "success": False,
                    "sql": sql,
                    "query_result": None,
                    "explanation": None,
                    "error": result["error"],
                }

            explanation = self.llm.explain_result(query, result["rows"])

            logger.info(f"===== NL2SQL 完整流程完成 =====")
            return {
                "success": True,
                "sql": sql,
                "query_result": result["rows"],
                "explanation": explanation,
                "error": None,
            }
        except Exception as e:
            logger.error(f"NL2SQL 流程异常: {e}")
            return {
                "success": False,
                "sql": None,
                "query_result": None,
                "explanation": None,
                "error": str(e),
            }

    @staticmethod
    def get_table_list() -> List[str]:
        """返回所有表名列表"""
        return ALL_TABLES.copy()
