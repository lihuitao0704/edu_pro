<template>
  <div class="dashboard-page">
    <section class="finance-page-intro dashboard-intro">
      <div>
        <span class="section-kicker">MULTI-AGENT CONTROL CENTER</span>
        <h1>金融智能运营中心</h1>
        <p>实时监控 Agent 协作、执行质量与财富服务经营指标。</p>
      </div>
      <div class="dashboard-live"><i /> 全部核心服务正常运行 <small>更新时间 16:36</small></div>
    </section>

    <section class="dashboard-metrics">
      <DashboardCard v-for="metric in platformMetrics" :key="metric.label" v-bind="metric" />
    </section>

    <section class="agent-directory-section">
      <header class="panel-title-row"><div><span class="section-kicker">AGENT FLEET</span><h2>Agent 管理中心</h2></div><button class="finance-secondary">查看运行日志</button></header>
      <div class="agent-directory"><AgentCard v-for="agent in agentDirectory" :key="agent.code" :agent="agent" /></div>
    </section>

    <section class="dashboard-main-grid">
      <AgentTrace :nodes="executionTrace" />
      <RiskPanel />
    </section>

    <section class="analytics-section">
      <header class="panel-title-row"><div><span class="section-kicker">BUSINESS ANALYTICS</span><h2>经营与服务洞察</h2></div><span class="data-freshness">数据延迟 &lt; 5 min</span></header>
      <div class="chart-grid">
        <ChartPanel title="Agent 调用趋势" eyebrow="REQUEST VOLUME" caption="近 7 日" :option="trendOption" />
        <ChartPanel title="客户诉求分布" eyebrow="INTENT MIX" caption="今日" :option="pieOption" />
        <ChartPanel title="风险控制维度" eyebrow="RISK POSTURE" caption="综合评分" :option="radarOption" />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { EChartsOption } from 'echarts'

import AgentCard from '../components/AgentCard.vue'
import AgentTrace from '../components/AgentTrace.vue'
import ChartPanel from '../components/ChartPanel.vue'
import DashboardCard from '../components/DashboardCard.vue'
import RiskPanel from '../components/RiskPanel.vue'
import { agentDirectory, executionTrace, intentMix, platformMetrics, requestTrend, riskRadar } from '../mocks/platform'

const axisStyle = { axisLine: { lineStyle: { color: '#263247' } }, axisLabel: { color: '#8190a8' }, splitLine: { lineStyle: { color: '#1c2738' } } }
const trendOption: EChartsOption = {
  grid: { left: 36, right: 14, top: 20, bottom: 24 },
  tooltip: { trigger: 'axis', backgroundColor: '#111827', borderColor: '#263247', textStyle: { color: '#e5edf9' } },
  xAxis: { type: 'category', data: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'], ...axisStyle },
  yAxis: { type: 'value', ...axisStyle },
  series: [{ type: 'line', smooth: true, data: requestTrend, symbol: 'none', lineStyle: { color: '#38bdf8', width: 3 }, areaStyle: { color: 'rgba(56,189,248,.16)' } }],
}
const pieOption: EChartsOption = {
  tooltip: { trigger: 'item', backgroundColor: '#111827', borderColor: '#263247', textStyle: { color: '#e5edf9' } },
  series: [{ type: 'pie', radius: ['48%', '72%'], label: { color: '#9aa8bd', formatter: '{b}\n{d}%' }, labelLine: { lineStyle: { color: '#40506a' } }, itemStyle: { borderColor: '#111827', borderWidth: 4 }, data: intentMix, color: ['#38bdf8', '#8b5cf6', '#f59e0b', '#34d399'] }],
}
const radarOption: EChartsOption = {
  radar: { indicator: [{ name: '适当性', max: 100 }, { name: '集中度', max: 100 }, { name: '流动性', max: 100 }, { name: '合规性', max: 100 }, { name: '预警响应', max: 100 }], axisName: { color: '#9aa8bd' }, splitArea: { areaStyle: { color: ['rgba(20,30,45,.4)'] } }, splitLine: { lineStyle: { color: '#29364a' } }, axisLine: { lineStyle: { color: '#29364a' } } },
  series: [{ type: 'radar', data: [{ value: riskRadar, areaStyle: { color: 'rgba(139,92,246,.22)' }, lineStyle: { color: '#a78bfa', width: 2 }, itemStyle: { color: '#c4b5fd' } }] }],
}
</script>
