<template>
  <article class="dashboard-metric-card" :class="`metric-${tone}`">
    <span>{{ label }}</span>
    <strong>{{ value }}</strong>
    <small>{{ trend }} 较昨日</small>
  </article>
</template>

<script setup lang="ts">
defineProps<{ label: string; value: string; trend: string; tone: string }>()
</script>
