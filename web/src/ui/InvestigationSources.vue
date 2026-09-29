<script setup lang="ts">
import { ref, watch } from 'vue'
import { coreApi, type CaseSnapshot, type InvestigationView } from '../client'
import InvestigationFindings from './InvestigationFindings.vue'
const props = defineProps<{ token: string; snapshot: CaseSnapshot }>()
const view = ref<InvestigationView | null>(null)
const loading = ref(false)
const error = ref('')
let generation = 0
const toolLabels: Record<string, string> = { get_order_line: '读取订单', get_shipment_trace: '核对物流', get_case_evidence: '读取工单材料', search_policy: '检索政策', read_policy: '读取政策原文' }
const statusLabels: Record<string, string> = { QUEUED: '等待调查', RUNNING: '正在调查', COMPLETED: '调查完成', FAILED: '调查失败', CANCELLED: '调查已取消', WAITING_CUSTOMER: '等待客户补证' }
const resultLabels: Record<string, string> = { LOST: '丢失', SIGNED: '已签收', DELAYED: '运输延误', RETURNED: '已退回', IN_TRANSIT: '运输中', DELIVERED: '已送达', PAID: '已支付' }
function facts(result: Record<string, unknown> | null) {
  if (!result) return []
  return Object.entries({ carrier_conclusion: '承运商结论', status: '记录状态', quantity: '商品数量', updated_at: '记录更新时间' })
    .filter(([key]) => typeof result[key] === 'string' || typeof result[key] === 'number')
    .map(([key, label]) => ({ label, value: resultLabels[String(result[key])] ?? String(result[key]) }))
}
async function reload() {
  const request = ++generation
  const { case_id: id, version } = props.snapshot.case
  view.value = null; error.value = ''; loading.value = true
  try {
    const result = await coreApi.investigation(props.token, id)
    if (request !== generation) return
    if (version !== result.case_version) { error.value = '工单版本已变化，请刷新工单后核对调查记录。'; return }
    view.value = result
  } catch { if (request === generation) error.value = '暂时无法读取调查记录，请稍后重试。' }
  finally { if (request === generation) loading.value = false }
}
watch(() => [props.token, props.snapshot.case.case_id, props.snapshot.case.version], reload, { immediate: true })
function cited(item: NonNullable<InvestigationView['investigation']>['observations'][number]) {
  const refs = props.snapshot.proposal?.evidence_refs
  return Array.isArray(refs) && refs.some(ref => ref?.observation_id === item.observation_id
    && ref.source_ref === item.source_ref && ref.source_version === item.source_version && ref.content_hash === item.content_hash)
}
</script>

<template>
  <section class="investigation-sources" aria-label="调查原始记录">
    <InvestigationFindings :snapshot="snapshot" :observations="view?.investigation?.observations ?? []" />
    <div class="sources-heading"><h3>调查原始记录</h3><button type="button" :disabled="loading" @click="reload">刷新记录</button></div>
    <p v-if="loading">正在读取已保存的调查记录…</p>
    <p v-else-if="error" role="status">{{ error }}</p>
    <p v-else-if="view?.availability === 'NOT_SCHEDULED'">当前材料版本没有关联调查；人工方案及人工决定请查看对应记录。</p>
    <p v-else-if="view?.availability === 'UNAVAILABLE'">调查服务暂不可用，或此历史调查没有可读取记录。不能据此认定未调查。</p>
    <template v-else-if="view?.investigation">
      <p>{{ statusLabels[view.investigation.status] || view.investigation.status }} · 第 {{ view.input_revision }} 版材料
        <span v-if="view.investigation.model_provider === 'mock'"> · mock 合成决策</span>
        <span v-else-if="view.investigation.model_provider"> · 模型提供方：{{ view.investigation.model_provider }}</span>
        <span v-else> · 模型来源未记录</span></p>
      <p class="sources-note">以下是调查当时保存的工具结果，可能与当前业务数据不同；记录存在不代表真实性已人工核验。</p>
      <p v-if="!view.investigation.observations.length">此调查没有可展示的已保存工具读取结果。</p>
      <details v-for="item in view.investigation.observations" :key="item.call_id">
        <summary>{{ toolLabels[item.tool_name] || item.tool_name }} <span v-if="cited(item)">· 本方案引用</span><span v-if="item.error_code"> · 读取失败</span></summary>
        <p>{{ item.source_ref }} · 版本 {{ item.source_version || '未提供' }} · {{ item.observed_at }}</p>
        <p v-if="item.body_omitted">正文超出显示上限，未提供；不能依据省略内容作出判断。</p>
        <p v-else-if="item.error_code">读取失败：{{ item.error_code }}</p>
        <template v-else><dl v-if="facts(item.result).length"><template v-for="fact in facts(item.result)" :key="fact.label"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></template></dl>
          <details class="source-body"><summary>展开完整原始结果</summary><pre>{{ JSON.stringify(item.result, null, 2) }}</pre></details>
        </template>
        <small>观察 {{ item.observation_id }} · 内容摘要 {{ item.content_hash || '无可引用摘要' }}</small>
      </details>
      <p v-if="view.investigation.truncated">仅展示前 40 条已保存记录，后续记录未显示。</p>
    </template>
  </section>
</template>

<style scoped>
.investigation-sources { padding: 16px 0; border-top: 1px solid #e8edf5; }
.sources-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.sources-heading h3 { margin: 0; }
.sources-heading button { background: #f3f7ff; color: #165bdb; border: 1px solid #dce7fa; border-radius: 6px; padding: 6px 10px; }
.investigation-sources p, .investigation-sources small { font-size: 12px; line-height: 1.65; color: #65758e; overflow-wrap: anywhere; }
.investigation-sources details { margin: 8px 0; padding: 10px 12px; background: #f7f9fc; border: 1px solid #e7edf5; border-radius: 8px; }
.investigation-sources summary { cursor: pointer; color: #285ba6; font-size: 13px; }
.investigation-sources pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; color: #33445c; }
.investigation-sources dl { display: grid; grid-template-columns: 100px 1fr; gap: 6px; font-size: 12px; }
.investigation-sources dt { color: #74829a; }.investigation-sources dd { margin: 0; color: #33445c; overflow-wrap: anywhere; }
</style>
