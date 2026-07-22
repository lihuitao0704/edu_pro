"""
LLM 客户端类 — 封装 OpenAI API 调用、SQL 生成、结果解读
"""

import os
import time
import logging
from typing import Optional, List, Dict
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    """LLM 调用客户端，支持 OpenAI API 和模拟模式"""

    def __init__(self):
        """初始化 LLM 客户端，从环境变量读取 API Key"""
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            self.mock_mode: bool = False
            self.client = OpenAI(api_key=api_key)
            logger.info("LLMClient 初始化完成，使用 OpenAI API")
        else:
            self.mock_mode: bool = True
            self.client = None
            print("⚠️ 未配置OpenAI API Key，使用模拟模式")
            logger.warning("未配置OpenAI API Key，使用模拟模式")

    def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_retries: int = 3,
    ) -> str:
        """调用 LLM 生成回复，支持指数退避重试"""
        if self.mock_mode:
            return "[模拟回复] 已收到您的请求，当前为模拟模式。"

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                logger.info(f"LLM 调用中... (第 {attempt + 1}/{max_retries} 次)")
                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=messages,
                    temperature=0.3,
                )
                result: str = response.choices[0].message.content
                logger.info("LLM 调用成功")
                return result
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(
                    f"LLM 调用失败 (第 {attempt + 1} 次): {e}，{wait}s 后重试"
                )
                if attempt < max_retries - 1:
                    time.sleep(wait)

        logger.error(f"LLM 调用全部失败: {last_error}")
        return f"LLM调用失败: {str(last_error)}"

    def generate_sql(self, user_query: str, schema_text: str) -> str:
        """根据自然语言和表结构生成 SQL 语句"""
        if self.mock_mode:
            return "SELECT * FROM `fin_product` WHERE `status` = '在售'"

        prompt = f"""你是一个SQL专家。根据以下表结构，将自然语言转为SQL语句。

【表结构】
{schema_text}

【规则】
1. 只允许SELECT查询
2. 字段名用反引号包裹
3. 字符串用单引号

【示例】
用户问：查询所有在售产品
SQL：SELECT * FROM `fin_product` WHERE `status` = '在售'

用户问：客户张三的持仓有哪些
SQL：SELECT h.* FROM `fin_holdings` h JOIN `sys_user` u ON h.`customer_id` = u.`id` WHERE u.`real_name` = '张三'

用户问：统计各产品类型的平均收益率
SQL：SELECT `product_type`, AVG(`expected_return`) FROM `fin_product` GROUP BY `product_type`

用户问：{user_query}
SQL："""

        logger.info(f"生成 SQL，用户查询: {user_query}")
        result = self.chat(prompt)
        result = result.replace("```sql", "").replace("```", "").strip()
        logger.info(f"生成 SQL: {result}")
        return result

    def explain_result(self, query: str, result) -> str:
        """对查询结果进行自然语言解读"""
        if isinstance(result, list) and len(result) == 0:
            return "查询结果为空。"

        if isinstance(result, dict) and "error" in result:
            return f"查询失败：{result['error']}"

        if self.mock_mode:
            count = len(result) if isinstance(result, list) else 1
            return f"【模拟解读】查询完成，共返回 {count} 条记录。"

        prompt = (
            f"用户问：{query}\n"
            f"查询结果：{result}\n"
            f"请用简洁、自然的语言解读这些数据。"
        )
        logger.info(f"解读查询结果，用户查询: {query}")
        return self.chat(prompt)
