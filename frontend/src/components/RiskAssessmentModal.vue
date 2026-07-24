<template>
  <Teleport to="body">
    <div class="modal-overlay" v-if="visible" @click.self="close">
      <div class="modal-container">
        <div class="modal-header">
          <div>
            <span class="eyebrow">RISK ASSESSMENT</span>
            <h2>投资者风险测评问卷</h2>
            <p>共 16 题 · 约需 3 分钟 · 用于适当性匹配</p>
          </div>
          <button class="quiet-button modal-close" @click="close">&times;</button>
        </div>
        <div class="modal-body">
          <LoadingPanel v-if="loading" text="加载问卷中…" />
          <template v-else>
            <!-- 进度条 -->
            <div class="quiz-progress">
              <div class="progress-bar"><div :style="{ width: `${(answeredCount / questions.length) * 100}%` }" /></div>
              <span>{{ answeredCount }} / {{ questions.length }}</span>
            </div>
            <!-- 题目列表 -->
            <div class="quiz-list">
              <div v-for="(q, qi) in questions" :key="q.q" class="quiz-item" :class="{ answered: answers[q.q] }">
                <p class="quiz-question"><strong>{{ q.q }}.</strong> {{ q.question }}</p>
                <div class="quiz-options">
                  <label
                    v-for="opt in q.options"
                    :key="Object.keys(opt)[0]"
                    :class="{ selected: answers[q.q] === Object.keys(opt)[0] }"
                  >
                    <input
                      type="radio"
                      :name="`q-${q.q}`"
                      :value="Object.keys(opt)[0]"
                      v-model="answers[q.q]"
                    />
                    <span>{{ Object.keys(opt)[0] }}. {{ Object.values(opt)[0] }}</span>
                  </label>
                </div>
              </div>
            </div>
          </template>
        </div>
        <div class="modal-footer">
          <button class="secondary-button" @click="close">取消</button>
          <button
            class="primary-button"
            :disabled="!allAnswered || submitting"
            @click="submit"
          >
            {{ submitting ? '提交中…' : '提交测评' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { get, post } from '../api/http'
import LoadingPanel from '../components/LoadingPanel.vue'
import { publishProfileUpdated } from '../utils/profile-events'

interface Question {
  q: number
  question: string
  options: Array<Record<string, any>>
}

const props = defineProps<{
  visible: boolean
  customerId: number
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'submitted': [result: any]
}>()

const questions = ref<Question[]>([])
const answers = reactive<Record<number, string>>({})
const loading = ref(false)
const submitting = ref(false)

const answeredCount = computed(() => Object.keys(answers).length)
const allAnswered = computed(() => questions.value.length > 0 && answeredCount.value === questions.value.length)

async function loadQuestionnaire() {
  loading.value = true
  try {
    const data = await get<{ items?: Question[]; data?: any }>('/risk/questionnaire')
    questions.value = (data as any).data || data || []
  } catch {
    questions.value = []
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!allAnswered.value || submitting.value) return
  submitting.value = true
  try {
    const payload = Object.entries(answers).map(([q, a]) => ({
      q: Number(q),
      a,
    }))
    const result = await post<any>('/risk/assessment', {
      customer_id: props.customerId,
      answers: payload,
    })
    publishProfileUpdated(props.customerId)
    emit('submitted', result)
    close()
  } catch {
    // error handled by parent
  } finally {
    submitting.value = false
  }
}

function close() {
  emit('update:visible', false)
}

// 每次打开时重置并重新加载
watch(
  () => props.visible,
  (val) => {
    if (val) {
      Object.keys(answers).forEach((k) => delete answers[Number(k)])
      loadQuestionnaire()
    }
  }
)
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(7, 27, 45, 0.55);
  display: grid;
  place-items: center;
  z-index: 999;
  padding: 20px;
}
.modal-container {
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 24px 60px rgba(15, 38, 52, 0.18);
  width: min(720px, 100%);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}
.modal-header {
  padding: 24px 28px 16px;
  border-bottom: 1px solid #dce4e7;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.modal-header h2 { margin: 4px 0 4px; font-family: Georgia, 'Noto Sans SC', serif; font-size: 22px; }
.modal-header p { margin: 0; color: #6d7c87; font-size: 13px; }
.modal-close { font-size: 24px; padding: 4px 12px !important; line-height: 1; }
.modal-body { padding: 20px 28px; overflow-y: auto; flex: 1; }
.modal-footer { padding: 16px 28px 20px; border-top: 1px solid #dce4e7; display: flex; justify-content: flex-end; gap: 10px; }
.quiz-progress { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
.progress-bar { flex: 1; height: 6px; border-radius: 3px; background: #eef2f3; overflow: hidden; }
.progress-bar > div { height: 100%; background: #0b7f78; border-radius: 3px; transition: width .3s; }
.quiz-progress span { font-size: 12px; color: #6d7c87; white-space: nowrap; }
.quiz-list { display: grid; gap: 18px; }
.quiz-item { padding: 14px 16px; border: 1px solid #dce4e7; border-radius: 12px; transition: border-color .2s; }
.quiz-item.answered { border-color: #b0d8d4; background: #f9fdfc; }
.quiz-question { margin: 0 0 10px; font-size: 14px; }
.quiz-options { display: grid; gap: 6px; }
.quiz-options label {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; border: 1px solid #dce4e7; border-radius: 8px;
  cursor: pointer; font-size: 13px; transition: background .15s, border-color .15s;
}
.quiz-options label:hover { background: #edf7f5; }
.quiz-options label.selected { border-color: #0b7f78; background: #dff3ef; font-weight: 600; }
.quiz-options input[type="radio"] { width: auto; accent-color: #0b7f78; }
</style>
