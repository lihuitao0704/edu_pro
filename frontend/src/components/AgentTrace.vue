<template>
  <section class="trace-panel">
    <header class="panel-title-row">
      <div><span class="section-kicker">AGENT TRACE</span><h3>请求执行链路</h3></div>
      <span class="trace-id">TRACE-4E9A28</span>
    </header>
    <ol class="trace-list">
      <li v-for="(node, index) in nodes" :key="node.name">
        <div class="trace-node-index">{{ String(index + 1).padStart(2, '0') }}</div>
        <div><strong>{{ node.name }}</strong><p>{{ node.action }}</p></div>
        <time>{{ node.duration }}</time>
        <span class="trace-result" :class="node.result">{{ node.result === 'success' ? '成功' : '处理中' }}</span>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import type { TraceNode } from '../mocks/platform'

defineProps<{ nodes: TraceNode[] }>()
</script>
