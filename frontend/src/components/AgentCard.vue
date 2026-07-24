<template>
  <article class="agent-status-card" :class="`accent-${agent.accent}`">
    <header>
      <span class="agent-code">{{ agent.code }}</span>
      <span class="agent-online" :class="agent.status.toLowerCase()"><i /> {{ agent.status }}</span>
    </header>
    <h3>{{ agent.name }}</h3>
    <p>{{ agent.description }}</p>
    <dl>
      <div><dt>今日调用</dt><dd>{{ agent.calls.toLocaleString() }}</dd></div>
      <div><dt>响应时间</dt><dd>{{ agent.latency }}</dd></div>
      <div><dt>成功率</dt><dd>{{ (agent.successRate * 100).toFixed(1) }}%</dd></div>
    </dl>
  </article>
</template>

<script setup lang="ts">
import type { AgentSummary } from '../mocks/platform'

defineProps<{ agent: AgentSummary }>()
</script>
