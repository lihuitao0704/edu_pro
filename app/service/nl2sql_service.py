"""
NL2SQL 数据分析服务 — 自然语言 → SQL → 执行 → 解读
"""

from app.config.database import SessionLocal
from app.tool.llm_client import LLMClient
from app.model import entities
from app.config.redis_client import get_redis_client
from app.config.settings import get_settings
from sqlalchemy import text
from typing import List, Dict, Optional, Tuple
import hashlib
import json
import re
import time
import logging

logger = logging.getLogger(__name__)

_settings = get_settings()

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

# 敏感列黑名单（禁止在 SELECT 中查询这些列）
SENSITIVE_COLUMNS = {
    "password", "password_hash", "pwd", "passwd",
    "api_key", "api_secret", "secret_key", "secret",
    "token", "access_token", "refresh_token",
    "private_key", "id_card", "身份证号",
}


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
            "评估": "fin_risk_assessment",
            "问卷": "fin_risk_assessment",
            "风险": "fin_risk_alert",
            "预警": "fin_risk_alert",
            "风控": "fin_risk_alert",
            "工单": "biz_work_order",
            "对话": "conversation_archive",
            "归档": "conversation_archive",
            "知识": "fin_knowledge_meta",
            "文档": "fin_knowledge_meta",
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

    @staticmethod
    def _get_foreign_keys() -> str:
        """从 INFORMATION_SCHEMA 查询外键关系，辅助 LLM 生成 JOIN"""
        logger.info("查询外键关系…")
        db = SessionLocal()
        try:
            sql = text(
                "SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
                "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL"
            )
            result = db.execute(sql)
            rows = result.fetchall()
            if not rows:
                return ""
            lines = ["【表关系】"]
            for row in rows:
                lines.append(f"`{row[0]}`.`{row[1]}` → `{row[2]}`.`{row[3]}`")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"外键查询失败: {e}")
            return ""
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
        foreign_keys = self._get_foreign_keys()
        examples = self._get_few_shot_examples()
        full_schema = schema + "\n" + foreign_keys + "\n" + examples
        sql = self.llm.generate_sql(query, full_schema)
        logger.info(f"生成 SQL: {sql}")
        return sql

    @staticmethod
    def _strip_sql_comments(sql: str) -> str:
        """去除 SQL 中的注释（防止绕过检测）"""
        # 去除 /* ... */ 块注释
        sql = re.sub(r'/\*[\s\S]*?\*/', '', sql)
        # 去除 -- 行注释
        sql = re.sub(r'--[^\n]*', '', sql)
        # 去除 # 行注释（MySQL 风格）
        sql = re.sub(r'#[^\n]*', '', sql)
        return sql.strip()

    @staticmethod
    def validate_sql(sql: str) -> Tuple[bool, str]:
        """SQL 安全校验（强化版）"""
        if not sql or not sql.strip():
            logger.warning("SQL 为空")
            return False, "SQL 语句为空"

        # 1. 先去除注释（防止注释绕过检测）
        clean_sql = NL2SQLService._strip_sql_comments(sql)
        sql_upper = clean_sql.upper().strip()

        # 2. 必须以 SELECT 开头
        if not sql_upper.startswith("SELECT"):
            logger.warning(f"SQL 非 SELECT 语句: {clean_sql[:50]}...")
            return False, "只允许 SELECT 查询"

        # 3. 禁止危险关键词（从 settings 读取，可扩展）
        forbidden_keywords = _settings.nl2sql.blocked_keywords_list
        # 额外加入运行时必须的禁止词
        extra_forbidden = ["UNION", "INTO", "LOAD_FILE", "SELECT INTO", "EXEC", "EXECUTE"]
        all_forbidden = set(forbidden_keywords) | set(extra_forbidden)

        for keyword in all_forbidden:
            if re.search(rf"\b{keyword}\b", sql_upper):
                logger.warning(f"SQL 包含禁止关键词: {keyword}")
                return False, f"禁止执行危险操作: {keyword}"

        # 4. 禁止查询敏感列
        sql_lower = clean_sql.lower()
        for col in SENSITIVE_COLUMNS:
            # 检查 SELECT 子句中是否包含敏感列
            if re.search(rf'\b{re.escape(col)}\b', sql_lower):
                logger.warning(f"SQL 查询了敏感列: {col}")
                return False, f"禁止查询敏感列: {col}"

        # 5. 禁止子查询访问敏感表（只允许 SELECT，不允许 INSERT/UPDATE/DELETE 子句）
        # 额外防御：检测多语句（分号后有第二个语句）
        if ";" in clean_sql.rstrip(";"):
            logger.warning("SQL 包含多语句")
            return False, "禁止执行多语句"

        logger.info("SQL 校验通过")
        return True, ""

    @staticmethod
    def execute_sql(sql: str) -> Dict:
        """执行 SQL 返回结果（行数从 settings 读取）"""
        max_rows = _settings.nl2sql.max_rows
        logger.info(f"执行 SQL: {sql[:100]}...")
        db = SessionLocal()
        try:
            result = db.execute(text(sql))
            columns = list(result.keys())

            # 过滤掉敏感列（二次防御，即使 validate 放行也可能有遗漏）
            safe_columns = [c for c in columns if c.lower() not in SENSITIVE_COLUMNS]
            if len(safe_columns) < len(columns):
                filtered_cols = set(columns) - set(safe_columns)
                logger.warning(f"执行时过滤敏感列: {filtered_cols}")

            rows = result.fetchmany(max_rows)
            data: List[Dict] = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                # 删除敏感列的值
                for col in SENSITIVE_COLUMNS:
                    row_dict.pop(col, None)
                    row_dict.pop(col.lower(), None)
                data.append(row_dict)

            logger.info(f"查询返回 {len(data)} 行")
            return {"columns": safe_columns, "rows": data, "row_count": len(data)}
        except Exception as e:
            logger.error(f"SQL 执行失败: {e}")
            return {"error": str(e)}
        finally:
            db.close()

    def query_and_explain(self, query: str, user_id: int = 0) -> Dict:
        """完整流程：生成 SQL → 校验 → 执行 → 解读（带 Redis 缓存）

        Args:
            query: 用户自然语言查询
            user_id: 用户 ID（用于缓存隔离，0 表示匿名）
        """
        t_start = time.time()
        logger.info(f"===== NL2SQL 完整流程开始 =====")
        logger.info(f"用户问题: {query}")

        # 生成缓存 key：nl2sql:{user_id}:{md5(query)}
        cache_key = f"nl2sql:{user_id}:{hashlib.md5(query.encode('utf-8')).hexdigest()}"

        # 尝试从 Redis 读取缓存
        r = None  # ← 提前初始化，避免作用域 bug
        try:
            r = get_redis_client()
            if r:
                cached = r.get(cache_key)
                if cached:
                    logger.info(f"命中缓存: {cache_key}")
                    return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis 读取缓存失败（不影响查询）: {e}")

        try:
            t1 = time.time()
            sql = self.generate_sql(query)
            t_generate = time.time() - t1

            valid, msg = self.validate_sql(sql)
            if not valid:
                return {
                    "success": False,
                    "sql": sql,
                    "query_result": None,
                    "explanation": None,
                    "error": msg,
                    "safety": {"select_only": False, "row_limit": True, "no_sensitive": False},
                }

            t2 = time.time()
            result = self.execute_sql(sql)
            t_execute = time.time() - t2

            if "error" in result:
                return {
                    "success": False,
                    "sql": sql,
                    "query_result": None,
                    "explanation": None,
                    "error": result["error"],
                    "safety": {"select_only": True, "row_limit": True, "no_sensitive": True},
                }

            t3 = time.time()
            explanation = self.llm.explain_result(query, result["rows"])
            t_explain = time.time() - t3

            exceeded = result.get("row_count", 0) >= _settings.nl2sql.max_rows

            response = {
                "success": True,
                "sql": sql,
                "query_result": result["rows"],
                "explanation": explanation,
                "error": None,
                "safety": {
                    "select_only": True,
                    "row_limit": not exceeded,
                    "no_sensitive": True,
                },
                "truncated": exceeded,
                "timing": {
                    "generate_ms": round(t_generate * 1000),
                    "execute_ms": round(t_execute * 1000),
                    "explain_ms": round(t_explain * 1000),
                    "total_ms": round((time.time() - t_start) * 1000),
                },
            }

            # 写入 Redis 缓存，TTL 从 settings 读取
            try:
                if r:
                    ttl = _settings.nl2sql.cache_ttl
                    r.setex(cache_key, ttl, json.dumps(response, ensure_ascii=False, default=str))
                    logger.info(f"写入缓存: {cache_key} (TTL={ttl}s)")
            except Exception as e:
                logger.warning(f"Redis 写入缓存失败（不影响查询）: {e}")

            logger.info(f"===== NL2SQL 完整流程完成 (总耗时 {response['timing']['total_ms']}ms) =====")
            return response
        except Exception as e:
            logger.error(f"NL2SQL 流程异常: {e}")
            return {
                "success": False,
                "sql": None,
                "query_result": None,
                "explanation": None,
                "error": str(e),
                "safety": {"select_only": False, "row_limit": False, "no_sensitive": False},
                "truncated": False,
            }

    @staticmethod
    def get_table_list() -> List[str]:
        """返回所有表名列表"""
        return ALL_TABLES.copy()
