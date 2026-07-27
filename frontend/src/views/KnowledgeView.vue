<template>
  <div class="page-stack">
    <section class="page-intro">
      <div><h2>让 Agent 使用可信知识</h2><p>文档上传后自动完成解析、切片、向量化和来源追踪。</p></div>
      <div class="milvus-state" :class="{ online: status?.milvus_connected }"><i /><span>Milvus</span><strong>{{ status?.milvus_connected ? 'ONLINE' : 'OFFLINE' }}</strong></div>
    </section>
    <section class="knowledge-grid">
      <div class="surface-card upload-card">
        <div class="card-heading"><h3>上传知识文档</h3></div>
        <label class="drop-zone">
          <input type="file" accept=".txt,.md,.docx" @change="selectFile" />
          <span class="upload-glyph">＋</span>
          <strong>{{ file?.name || '选择或拖入文档' }}</strong>
          <small>TXT、Markdown、DOCX · 来源将随回答展示</small>
        </label>
        <label>知识类型<select v-model="knowledgeType"><option>FAQ</option><option>产品说明</option><option>政策法规</option><option>操作指南</option></select></label>
        <button class="primary-button" :disabled="!file || uploading" @click="upload">{{ uploading ? '正在入库…' : '上传并向量化' }}</button>
      </div>
      <div class="surface-card collection-card">
        <div class="card-heading"><h3>向量集合状态</h3></div>
        <div class="collection-list">
          <div v-for="(count, name) in status?.collections" :key="name"><span><i />{{ name }}</span><strong>{{ count ?? '—' }}</strong></div>
        </div>
      </div>
    </section>
    <ErrorAlert :message="error" />
    <section class="surface-card">
      <div class="card-heading split"><div><h3>知识文档</h3></div><button class="secondary-button" @click="load">刷新</button></div>
      <LoadingPanel v-if="loading" />
      <div v-else class="knowledge-list">
        <article v-for="item in items" :key="item.id">
          <span class="doc-icon">文</span>
          <div><strong>{{ item.title }}</strong><p>{{ item.knowledge_type }} · {{ item.source_file || '在线文档' }}</p></div>
          <span class="status-chip">{{ item.status }}</span>
          <time>{{ item.create_time?.slice(0, 10) }}</time>
          <button class="danger-link" @click="deleteItem(item.id)">删除</button>
        </article>
        <EmptyState v-if="!items.length" title="知识库为空" description="上传第一份可信业务文档。" />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { get, post, remove } from '../api/http'
import EmptyState from '../components/EmptyState.vue'
import ErrorAlert from '../components/ErrorAlert.vue'
import LoadingPanel from '../components/LoadingPanel.vue'

const file = ref<File | null>(null)
const knowledgeType = ref('产品说明')
const uploading = ref(false)
const loading = ref(false)
const error = ref('')
const items = ref<any[]>([])
const status = ref<{ milvus_connected: boolean; collections: Record<string, number | null> } | null>(null)

function selectFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [library, vectorStatus] = await Promise.all([
      get<{ items: any[] }>('/knowledge/list?page=1&size=100'),
      get<{ milvus_connected: boolean; collections: Record<string, number | null> }>('/knowledge/status'),
    ])
    items.value = library.items
    status.value = vectorStatus
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '知识库加载失败'
  } finally {
    loading.value = false
  }
}

async function upload() {
  if (!file.value) return
  uploading.value = true
  error.value = ''
  try {
    const body = new FormData()
    body.append('file', file.value)
    body.append('knowledge_type', knowledgeType.value)
    body.append('title', file.value.name)
    await post('/knowledge/upload', body)
    file.value = null
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '文档上传失败'
  } finally {
    uploading.value = false
  }
}

async function deleteItem(id: number) {
  if (!window.confirm('确认删除该文档及对应向量？')) return
  try {
    await remove(`/knowledge/${id}`)
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '文档删除失败'
  }
}

onMounted(load)
</script>
