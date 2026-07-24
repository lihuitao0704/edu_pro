<template>
  <section class="recommendation-card">
    <div class="recommendation-topline">
      <span>AI 配置建议</span>
      <b>{{ recommendation.risk_level }}</b>
    </div>
    <h4>{{ recommendation.title }}</h4>
    <div class="recommendation-product">
      <span>建议产品</span>
      <strong>{{ recommendation.product }}</strong>
      <em>{{ recommendation.allocation }}</em>
    </div>
    <p>{{ recommendation.rationale }}</p>
  </section>
</template>

<script setup lang="ts">
import type { Recommendation } from '../api/chat'

defineProps<{ recommendation: Recommendation }>()
</script>
