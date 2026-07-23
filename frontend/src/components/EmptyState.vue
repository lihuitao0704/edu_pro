<template>
  <div class="state-panel empty-state">
    <div class="state-symbol">∅</div>
    <strong>{{ title }}</strong>
    <p>{{ description }}</p>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{ title?: string; description?: string }>(),
  { title: '暂无数据', description: '调整筛选条件或稍后重试。' },
)
</script>
