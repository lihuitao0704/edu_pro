<template>
  <Teleport to="body">
    <div class="dt-overlay" @click.self="$emit('close')">
      <section class="dt-dialog" ref="dialogRef">
        <header class="dt-header">
          <div>
            <span class="eyebrow">QUERY RESULT</span>
            <h2>{{ title }}</h2>
          </div>
          <button class="dt-close" @click="$emit('close')">✕</button>
        </header>

        <!-- SQL 可折叠 -->
        <div class="dt-sql-bar">
          <button class="quiet-button" @click="sqlOpen = !sqlOpen">
            {{ sqlOpen ? '▼' : '▶' }} SQL 查询语句
          </button>
          <button v-if="sqlOpen" class="text-button" @click="copySql">📋 复制</button>
        </div>
        <pre v-if="sqlOpen && sql" class="dt-sql-code"><code>{{ sql }}</code></pre>

        <!-- 表格 -->
        <div class="dt-table-wrap">
          <table v-if="columns.length">
            <thead>
              <tr>
                <th class="dt-row-num">#</th>
                <th v-for="col in columns" :key="col" :style="colWidth(col)">{{ colLabel(col) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in displayRows" :key="(page - 1) * pageSize + i">
                <td class="dt-row-num">{{ (page - 1) * pageSize + i + 1 }}</td>
                <td v-for="col in columns" :key="col">{{ formatTableCell(row[col], col) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="dt-empty">暂无数据</div>
        </div>

        <footer class="dt-footer">
          <span class="dt-count">共 {{ rows.length }} 条记录</span>
          <div v-if="totalPages > 1" class="dt-pager">
            <button :disabled="page <= 1" @click="page--">← 上一页</button>
            <span>{{ page }} / {{ totalPages }}</span>
            <button :disabled="page >= totalPages" @click="page++">下一页 →</button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { formatTableCell } from '../utils/table-format'

const props = defineProps<{
  rows: Record<string, any>[]
  sql?: string
  title?: string
}>()

const emit = defineEmits<{ close: [] }>()

const page = ref(1)
const pageSize = 50
const sqlOpen = ref(false)
const dialogRef = ref<HTMLElement>()

// Escape 关闭
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))

const SENSITIVE_KEYWORDS = ['password', 'salt', 'secret', 'token', 'private_key', 'api_key']

const columns = computed(() => {
  if (!props.rows.length) return []
  return Object.keys(props.rows[0]).filter(k => !SENSITIVE_KEYWORDS.some(s => k.toLowerCase().includes(s)))
})

const totalPages = computed(() => Math.max(1, Math.ceil(props.rows.length / pageSize)))
const displayRows = computed(() => props.rows.slice((page.value - 1) * pageSize, page.value * pageSize))

const COLUMN_ALIAS: Record<string, string> = {
  id: '编号', username: '用户名', real_name: '姓名', user_type: '客户类型',
  employee_role: '员工角色', customer_level: '客户等级', phone: '手机号',
  email: '邮箱', status: '状态', balance: '账户余额', age: '年龄',
  education: '学历', occupation: '职业', create_time: '创建时间',
  update_time: '更新时间', total_assets: '总资产', risk_level: '风险等级',
  product_name: '产品名称', product_type: '产品类型', shares: '持有份额',
  current_value: '当前市值', profit_loss: '盈亏', profit_ratio: '收益率',
  transaction_type: '交易类型', amount: '交易金额', product_code: '产品代码',
  product_id: '产品ID', customer_id: '客户ID', customer_name: '客户名称',
  alert_level: '预警等级', alert_count: '预警次数', rule_name: '规则名称',
  trigger_reason: '触发原因', summary: '摘要', description: '描述',
}

function colLabel(key: string): string {
  return COLUMN_ALIAS[key] || key.replace(/_/g, ' ')
}

const COL_WIDTH: Record<string, string> = {
  id: '60px', age: '60px', customer_id: '70px', product_id: '70px',
  user_id: '60px', balance: '130px', total_assets: '130px', amount: '120px',
  current_value: '130px', profit_loss: '110px', shares: '120px',
  phone: '120px', status: '70px', risk_level: '80px', alert_level: '80px',
  product_code: '110px', transaction_type: '90px',
  create_time: '150px', update_time: '150px',
}

function colWidth(key: string): Record<string, string> | undefined {
  const w = COL_WIDTH[key]
  return w ? { width: w, minWidth: w } : undefined
}

function copySql() {
  if (props.sql) navigator.clipboard.writeText(props.sql)
}
</script>

<style scoped>
.dt-overlay {
  position: fixed; inset: 0; z-index: 1000;
  display: grid; place-items: center;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  padding: 20px;
}
.dt-dialog {
  width: min(95vw, 1200px); max-height: 85vh;
  display: flex; flex-direction: column;
  border-radius: 14px;
  background: #0f1929;
  border: 1px solid #263247;
  box-shadow: 0 24px 80px rgba(0,0,0,.5);
}
.dt-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 20px 24px 0;
}
.dt-header h2 { margin: 4px 0 0; color: #eef6ff; font-size: 16px; }
.dt-close {
  width: 32px; height: 32px; border: 1px solid #334155; border-radius: 8px;
  color: #94a3b8; background: transparent; font-size: 14px; cursor: pointer;
}
.dt-close:hover { color: #e2e8f0; background: #1e293b; }
.dt-sql-bar {
  display: flex; gap: 8px; align-items: center;
  margin: 12px 24px 0;
}
.dt-sql-bar .quiet-button {
  padding: 4px 10px; border: 1px solid #334155; border-radius: 6px;
  color: #94a3b8; background: transparent; font-size: 11px; cursor: pointer;
}
.dt-sql-bar .quiet-button:hover { color: #c9d5e5; border-color: #38bdf8; }
.dt-sql-bar .text-button {
  padding: 4px 10px; border: 1px solid #334155; border-radius: 6px;
  color: #94a3b8; background: transparent; font-size: 11px; cursor: pointer;
}
.dt-sql-bar .text-button:hover { color: #bae6fd; border-color: #38bdf8; }
.dt-sql-code {
  margin: 8px 24px 0; padding: 12px 14px;
  border-radius: 8px; background: #0a1525; overflow-x: auto;
}
.dt-sql-code code { color: #bae6fd; font-size: 12px; word-break: break-all; white-space: pre-wrap; }
.dt-table-wrap {
  flex: 1; overflow: auto; margin: 12px 24px;
  border: 1px solid #1e293b; border-radius: 10px;
}
.dt-table-wrap table { width: 100%; border-collapse: collapse; font-size: 12px; }
.dt-table-wrap th {
  position: sticky; top: 0; z-index: 1;
  padding: 10px 12px; text-align: left;
  color: #94a3b8; background: #0a1525; border-bottom: 1px solid #1e293b;
  font-weight: 600; white-space: nowrap;
}
.dt-table-wrap td { padding: 8px 12px; color: #c9d5e5; border-bottom: 1px solid #1a273a; }
.dt-table-wrap tr:hover td { background: rgba(56, 189, 248, 0.04); }
.dt-row-num { color: #4a5a70; width: 40px; min-width: 40px; text-align: center; }
.dt-empty { padding: 40px; text-align: center; color: #64748b; }
.dt-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 24px 16px;
}
.dt-count { color: #4a5a70; font-size: 11px; }
.dt-pager { display: flex; align-items: center; gap: 12px; }
.dt-pager button {
  padding: 6px 14px; border: 1px solid #334155; border-radius: 8px;
  color: #c9d5e5; background: transparent; font-size: 12px; cursor: pointer;
}
.dt-pager button:disabled { opacity: .4; cursor: not-allowed; }
.dt-pager button:hover:not(:disabled) { border-color: #38bdf8; }
.dt-pager span { color: #64748b; font-size: 12px; }
</style>
