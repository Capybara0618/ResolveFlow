<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '../client'
import { operationsApi, type OperationsRun, type OperationsDetail, type OperationsEvent } from '../support-operations'
import { stamp, tail } from '../support-view'
const props = defineProps<{ token: string }>()
const emit = defineEmits<{ expired: [] }>()
const runs = ref<OperationsRun[]>([]), detail = ref<OperationsDetail | null>(null)
const selected = ref(''), loading = ref(false), reading = ref(false), error = ref('')
let alive = true, listing = 0, opening = 0
onBeforeUnmount(() => { alive = false; ++listing; ++opening })
const status = (value: string) => ({ PENDING: '等待处理', RUNNING: '处理中', SUCCEEDED: '已答复', FAILED: '未完成', STALE: '输入已更新' } as Record<string, string>)[value] ?? '状态待核实'
const metric = (value: number | null) => value === null ? '未记录' : value
const sourceNames: Record<string, string> = { ORDER: '订单', SHIPMENT: '物流', POLICY: '政策', KNOWLEDGE: '指南', CONVERSATION: '已共享对话' }
function eventLabel(event: OperationsEvent) {
  const action = ({ ORDER: '查询订单', SHIPMENT: '查询物流', POLICY: '检索政策', GUIDE: '查阅指南', HISTORY: '查阅相关记录' } as Record<string, string>)[event.category ?? ''] ?? '读取资料'
  return ({ 'activity.started': `${action} · 开始`, 'activity.completed': `${action} · 已返回`, 'turn.accepted': '接收咨询', 'answer.started': '生成答复', 'answer.reset': '重新生成候选答复', 'answer.committed': '答复已保存', 'answer.failed': '本次未能完成答复', 'answer.stale': '输入变化，原答复停止发布' } as Record<string, string>)[event.kind] ?? '处理事件'
}
function fail(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) emit('expired')
  error.value = cause instanceof ApiError ? cause.message : '运行记录暂时无法读取，请重试。'
}
async function open(id: string) {
  const request = ++opening, token = props.token
  selected.value = id; detail.value = null; reading.value = true; error.value = ''
  try { const value = await operationsApi.read(token, id); if (alive && request === opening) detail.value = value }
  catch (cause) { if (alive && request === opening) fail(cause) }
  finally { if (alive && request === opening) reading.value = false }
}
async function load() {
  const request = ++listing, token = props.token
  loading.value = true; error.value = ''
  try {
    const value = await operationsApi.list(token)
    if (!alive || request !== listing) return
    runs.value = value.items
    if (selected.value && runs.value.some(run => run.run_id === selected.value)) await open(selected.value)
    else { ++opening; selected.value = ''; detail.value = null; reading.value = false }
  } catch (cause) { if (alive && request === listing) fail(cause) }
  finally { if (alive && request === listing) loading.value = false }
}
watch(() => props.token, () => { ++opening; selected.value = ''; detail.value = null; runs.value = []; void load() }, { immediate: true })
</script>

<template>
  <section class="support-operations">
    <header class="foundation-heading"><div><h1>客服运行记录</h1><p>最近50次咨询的处理过程 · 已脱敏</p></div><button :disabled="loading" @click="load">{{ loading ? '读取中…' : '刷新' }}</button></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <div class="operations-layout">
      <div class="operations-list"><table class="foundation-table"><thead><tr><th>时间 / 运行</th><th>店铺</th><th>模式</th><th>结果</th></tr></thead><tbody><tr v-for="run in runs" :key="run.run_id" :class="{ selected: selected === run.run_id }"><td><button data-run :aria-pressed="selected === run.run_id" @click="open(run.run_id)">{{ stamp(run.created_at, true) }}<small>#{{ tail(run.run_id) }}</small></button></td><td>{{ run.merchant_id }}</td><td>{{ run.mode === 'mock' ? '脚本模型' : run.mode === 'live' ? '真实模型' : '未记录' }}</td><td>{{ status(run.status) }}</td></tr></tbody></table><p v-if="!loading && !runs.length" class="empty">暂无运行记录。</p></div>
      <aside v-if="detail" data-run-detail class="operations-detail"><h2>{{ detail.run.merchant_id }} · {{ status(detail.run.status) }}</h2><p class="operations-id">{{ detail.run.run_id }}</p><dl><div><dt>模型请求</dt><dd>{{ metric(detail.run.model_requests) }}</dd></div><div><dt>业务工具尝试</dt><dd>{{ metric(detail.run.tool_attempts) }}</dd></div><div><dt>本地读取</dt><dd>{{ metric(detail.run.local_reads) }}</dd></div></dl>
        <p v-if="detail.run.reason">停止原因：{{ detail.run.reason }}</p><p class="operations-sources">已发布答复的依据：<template v-if="Object.keys(detail.run.source_counts).length"><span v-for="(count, kind) in detail.run.source_counts" :key="kind">{{ sourceNames[kind] ?? '其他' }} {{ count }}</span></template><template v-else>未记录</template></p>
        <h3>处理过程</h3><ol><li v-for="(event, index) in detail.events" :key="index"><span>{{ eventLabel(event) }}</span><small>{{ stamp(event.created_at) }}</small></li></ol><p v-if="!detail.events.length">该次运行没有保存可展示的过程事件。</p><p v-if="detail.events_truncated">仅显示最近200条过程事件。</p>
      </aside><aside v-else class="operations-detail operations-empty">{{ reading ? '正在读取处理过程…' : '选择一次运行查看处理过程' }}</aside>
    </div>
  </section>
</template>

<style scoped>
.operations-layout { display: grid; grid-template-columns: minmax(420px, 1.2fr) minmax(320px, 1fr); gap: 24px; align-items: start; }
.operations-list { overflow: auto; max-height: 70vh; }
.operations-list table { margin: 0; }
.operations-list button { text-align: left; background: transparent; border: 0; cursor: pointer; color: #244b78; }
.operations-list button small { display: block; margin-top: 4px; color: #77859a; }
tr.selected { background: #eef4fa; }
.operations-detail { background: white; border: 1px solid #e1e7ee; border-radius: 10px; padding: 22px; max-height: 70vh; overflow: auto; }
.operations-detail h2 { font-size: 18px; margin: 0; }.operations-detail h3 { font-size: 15px; margin-top: 24px; }
.operations-detail p { font-size: 12px; color: #6e7e91; line-height: 1.7; overflow-wrap: anywhere; }
.operations-id { font-family: monospace; }dl { display: flex; flex-wrap: wrap; gap: 24px; margin: 20px 0; }dt { color: #6e7e91; font-size: 12px; }dd { font-size: 20px; margin: 5px 0; }
.operations-sources span { display: inline-block; margin-right: 12px; }ol { padding-left: 20px; }li { padding: 8px 0; font-size: 14px; }li small { display: block; color: #77859a; margin-top: 4px; font-size: 11px; }.operations-empty { color: #77859a; }
@media(max-width:1100px) { .operations-layout { grid-template-columns: 1fr; } }
</style>
