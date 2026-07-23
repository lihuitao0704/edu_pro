<template>
  <div v-if="message" class="error-alert" role="alert">
    <span>!</span>
    <div>
      <strong>操作未完成</strong>
      <p>{{ message }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ message: string }>()
</script>
