<template>
  <Transition name="intro-fade">
    <section v-if="visible" class="app-intro" data-testid="app-intro" aria-label="平台正在启动" aria-modal="true" role="dialog">
      <div class="intro-grid" aria-hidden="true" />
      <div class="intro-orb intro-orb-one" aria-hidden="true" />
      <div class="intro-orb intro-orb-two" aria-hidden="true" />
      <div class="intro-content">
        <span class="intro-mark" aria-hidden="true">F</span>
        <span class="intro-name">FINTELLIGENCE</span>
        <p id="intro-status">智能投顾系统正在就绪</p>
        <span class="intro-progress" aria-hidden="true"><i /></span>
        <button ref="skipButton" type="button" @keydown.tab.prevent="focusSkip" @click="$emit('complete')">跳过开场</button>
      </div>
    </section>
  </Transition>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps<{ visible: boolean }>()
defineEmits<{ complete: [] }>()

const skipButton = ref<HTMLButtonElement>()
function focusSkip() { skipButton.value?.focus() }
function scheduleFocus() { if (props.visible) void nextTick(focusSkip) }

onMounted(scheduleFocus)
watch(() => props.visible, scheduleFocus)
</script>

<style scoped>
.app-intro { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; overflow: hidden; color: #172033; background: #f5f7fb; }
.intro-grid { position: absolute; inset: 0; opacity: .6; background-image: linear-gradient(rgba(52,70,168,.055) 1px, transparent 1px), linear-gradient(90deg, rgba(52,70,168,.055) 1px, transparent 1px); background-size: 48px 48px; mask-image: radial-gradient(circle at center, #000 0%, transparent 73%); }
.intro-orb { position: absolute; width: 38vw; aspect-ratio: 1; border-radius: 999px; filter: blur(5px); opacity: .38; }.intro-orb-one { top: -21vw; right: -10vw; background: radial-gradient(circle, rgba(133,146,237,.42), transparent 67%); }.intro-orb-two { bottom: -23vw; left: -12vw; background: radial-gradient(circle, rgba(102,190,210,.24), transparent 66%); }
.intro-content { position: relative; z-index: 1; display: grid; justify-items: center; min-width: min(320px, 84vw); text-align: center; animation: intro-rise .72s cubic-bezier(.2,.72,.2,1) both; }.intro-mark { display: grid; place-items: center; width: 56px; height: 56px; border: 1px solid rgba(52,70,168,.22); border-radius: 16px; color: #3446a8; background: rgba(255,255,255,.7); box-shadow: 0 18px 45px rgba(38,54,112,.13); font-size: 27px; font-weight: 650; }.intro-name { margin-top: 20px; font-size: 12px; font-weight: 800; letter-spacing: .2em; }.intro-content p { margin: 9px 0 20px; color: #667085; font-size: 13px; }.intro-progress { display: block; width: 140px; height: 2px; overflow: hidden; border-radius: 99px; background: rgba(52,70,168,.12); }.intro-progress i { display: block; width: 42%; height: 100%; border-radius: inherit; background: #3446a8; animation: intro-progress 1.05s cubic-bezier(.5,0,.5,1) infinite; }.intro-content button { margin-top: 26px; border: 0; color: #667085; background: transparent; font-size: 12px; text-decoration: underline; text-underline-offset: 3px; }.intro-content button:focus-visible { outline: 2px solid #3446a8; outline-offset: 5px; border-radius: 4px; }.intro-fade-enter-active, .intro-fade-leave-active { transition: opacity .32s ease; }.intro-fade-enter-from, .intro-fade-leave-to { opacity: 0; }
@keyframes intro-rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } } @keyframes intro-progress { from { transform: translateX(-120%); } to { transform: translateX(350%); } } @media (prefers-reduced-motion: reduce) { .intro-content, .intro-progress i { animation: none; } }
</style>
