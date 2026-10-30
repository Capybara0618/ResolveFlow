<script setup lang="ts">
import ListPagination from './ListPagination.vue'
import { useCursorPages } from '../cursor-pages'
import { onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '../client'
import { operationsApi, type OperationsRun, type OperationsDetail, type OperationsEvent } from '../support-operations'
import { stamp, tail } from '../support-view'
const {pageIndex,pageCursor,acceptPage,resetPages}=useCursorPages<string>()
const next = ref<string|null>(null), query=ref(''), filter=ref('')
let applied={query:'',status:''}
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
async function load(index = pageIndex.value, search = applied) {
  const request = ++listing, token = props.token
  loading.value = true; error.value = ''
  try {
    const value = await operationsApi.list(token,{before:pageCursor(index),...search})
    if (!alive || request !== listing) return
    runs.value = value.items;next.value=value.next_before??null;acceptPage(index,next.value);applied={...search}
    if (selected.value && runs.value.some(run => run.run_id === selected.value)) await open(selected.value)
    else { ++opening; selected.value = ''; detail.value = null; reading.value = false }
  } catch (cause) { if (alive && request === listing) fail(cause) }
  finally { if (alive && request === listing) loading.value = false }
}
watch(() => props.token, () => { resetPages();next.value=null;query.value='';filter.value='';applied={query:'',status:''};++opening; selected.value = ''; detail.value = null; runs.value = []; void load() }, { immediate: true })
</script>

<template>
  <section class="support-operations">
    <header class="foundation-heading"><div><h1>客服运行记录</h1></div><button :disabled="loading" @click="load()">{{ loading ? '读取中…' : '刷新' }}</button></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <form class="operations-filters foundation-actions" @submit.prevent="load(0,{query:query.trim(),status:filter})"><input v-model="query" aria-label="搜索运行或店铺" placeholder="搜索店铺或运行编号" maxlength="100" :disabled="loading" /><select v-model="filter" aria-label="运行状态" :disabled="loading"><option value="">全部状态</option><option v-for="s in ['PENDING','RUNNING','SUCCEEDED','FAILED','STALE']" :key="s" :value="s">{{ status(s) }}</option></select><button :disabled="loading">查询</button></form>
    <div class="operations-layout">
      <div class="operations-list"><table class="foundation-table"><thead><tr><th>时间 / 运行</th><th>店铺</th><th>模式</th><th>结果</th></tr></thead><tbody><tr v-for="run in runs" :key="run.run_id" :class="{ selected: selected === run.run_id }"><td><button data-run :aria-pressed="selected === run.run_id" @click="open(run.run_id)">{{ stamp(run.created_at, true) }}<small>#{{ tail(run.run_id) }}</small></button></td><td>{{ run.merchant_id }}</td><td>{{ run.mode === 'mock' ? '脚本模型' : run.mode === 'live' ? '真实模型' : '未记录' }}</td><td>{{ status(run.status) }}</td></tr></tbody></table><ListPagination :page="pageIndex" :has-next="!!next" :disabled="loading" label="客服运行分页" @change="load" /><p v-if="!loading && !error && !runs.length" class="empty">暂无运行记录。</p></div>
      <aside v-if="detail" data-run-detail class="operations-detail"><h2>{{ detail.run.merchant_id }} · {{ status(detail.run.status) }}</h2><p class="operations-id">{{ detail.run.run_id }}</p><dl><div><dt>模型请求</dt><dd>{{ metric(detail.run.model_requests) }}</dd></div><div><dt>业务工具尝试</dt><dd>{{ metric(detail.run.tool_attempts) }}</dd></div><div><dt>本地读取</dt><dd>{{ metric(detail.run.local_reads) }}</dd></div></dl>
        <p v-if="detail.run.reason">停止原因：{{ detail.run.reason }}</p><p class="operations-sources">已发布答复的依据：<template v-if="Object.keys(detail.run.source_counts).length"><span v-for="(count, kind) in detail.run.source_counts" :key="kind">{{ sourceNames[kind] ?? '其他' }} {{ count }}</span></template><template v-else>未记录</template></p>
        <h3>处理过程</h3><ol><li v-for="(event, index) in detail.events" :key="index"><span>{{ eventLabel(event) }}</span><small>{{ stamp(event.created_at) }}</small></li></ol><p v-if="!detail.events.length">该次运行没有保存可展示的过程事件。</p><p v-if="detail.events_truncated">仅显示最近200条过程事件。</p>
      </aside><aside v-else class="operations-detail operations-empty">{{ reading ? '正在读取处理过程…' : '选择一次运行查看处理过程' }}</aside>
    </div>
  </section>
</template>

<style scoped>
.operations-layout { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(300px, 1fr); gap: 24px; align-items: start; }
.operations-list{min-width:0;overflow-x:auto}.operations-filters{margin:0 0 24px}.operations-filters input{width:min(320px,100%)}.operations-list .foundation-table{min-width:420px}
.operations-list table { margin: 0; }
.operations-list button { text-align: left; background: transparent; border: 0; cursor: pointer; color: var(--rf-muted); }
.operations-list button small { display: block; margin-top: 4px; color: var(--rf-muted); }
tr.selected { background: var(--rf-accent-soft); }
.operations-detail { background: white; border: 1px solid var(--rf-line); border-radius: 10px; padding: 22px; max-height: 70vh; overflow: auto; }
.operations-detail h2 { font-size: 18px; margin: 0; }.operations-detail h3 { font-size: 15px; margin-top: 24px; }
.operations-detail p { font-size: 14px; color: var(--rf-muted); line-height: 1.7; overflow-wrap: anywhere; }
.operations-id { font-family: monospace; }dl { display: flex; flex-wrap: wrap; gap: 24px; margin: 20px 0; }dt { color: var(--rf-muted); font-size: 14px; }dd { font-size:22px;font-weight:500;font-variant-numeric:tabular-nums;margin:5px 0; }
.operations-sources span { display: inline-block; margin-right: 12px; }ol { padding-left: 20px; }li { padding: 8px 0; font-size: 14px; }li small { display: block; color: var(--rf-muted); margin-top: 4px; font-size: 12px; }.operations-empty { color: var(--rf-muted); }
@media(max-width:1100px) { .operations-layout { grid-template-columns: 1fr; } }
</style>
