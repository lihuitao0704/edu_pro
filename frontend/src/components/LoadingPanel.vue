<template>
  <div class="state-panel" role="status">
    <span class="loading-ring" />
    <p>{{ text }}</p>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ text?: string }>(), { text: '正在加载数据…' })
</script>
