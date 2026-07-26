<template>
  <aside class="risk-panel">
    <header><span class="section-kicker">RISK WATCH</span><h3>风险关注事项</h3></header>
    <div class="risk-score"><strong>{{ totalAlerts }}</strong><span>累计风险预警</span><em>实时汇总</em></div>
    <ul>
      <li v-for="item in normalizedDistribution" :key="item.name">
        <i :class="item.name" />
        <span><strong>{{ item.label }}</strong><small>{{ item.count }} 条预警</small></span>
      </li>
      <li v-if="!normalizedDistribution.length">
        <span><strong>暂无风险分布数据</strong><small>请检查风险统计服务</small></span>
      </li>
    </ul>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  totalAlerts: number
  distribution: Array<{ name: string; count: number; label?: string }>
}>()

const normalizedDistribution = computed(() => props.distribution.map(item => ({
  ...item,
  label: item.label || ({ high: '高风险', medium: '中风险', low: '低风险' }[item.name] || item.name),
})))
</script>
