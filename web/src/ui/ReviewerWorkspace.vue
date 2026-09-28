<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, coreApi, type CaseSnapshot, type ReviewContext, type ReviewerAction } from '../client'
import ReviewDialog from './ReviewDialog.vue'
import { formatMinorUnits } from '../money'

const props = defineProps<{ token: string; snapshot: CaseSnapshot; busy: boolean }>()
const emit = defineEmits<{ changed: []; working: [value: boolean] }>()
const context = ref<ReviewContext | null>(null)
const loading = ref(false)
const error = ref('')
const message = ref('')
const target = ref<CaseSnapshot | null>(null)
const targetContext = ref<ReviewContext | null>(null)
const action = ref<ReviewerAction['action'] | null>(null)
const reason = ref('')
const evidenceIds = ref<string[]>([])
const policyIds = ref<string[]>([])
const submitting = ref(false)
const executionLabels: Record<string, string> = { AUTHORIZED: '已批准，等待执行', EXECUTING: '退款执行中', RECONCILING: '退款结果待确认', CLOSED_SUCCESS: '模拟退款成功' }
const outcomeLabels: Record<string, string> = { SUCCEEDED: '模拟退款成功', FAILED: '退款明确失败', UNKNOWN: '退款结果待确认' }
const labels = { MANUAL_PROPOSAL: '提交人工退款方案', REJECT: '拒绝申请', REQUEST_INFO: '要求补充材料' }
const availableEvidence = computed(() => target.value?.evidence.filter(item => item.source_ref && item.source_version && item.content_hash) ?? [])
const key = (rule: ReviewContext['policy_rules'][number]) => `${rule.bundle_id}/${rule.rule_id}`
let generation = 0
async function reload() {
  const request = ++generation
  const version = props.snapshot.case.version
  const id = props.snapshot.case.case_id
  context.value = null; loading.value = true; error.value = ''
  try {
    const result = await coreApi.reviewContext(props.token, id)
    if (request !== generation) return
    if (result.case_version !== version) {
      error.value = '工单已变化，请刷新后查看当前操作。'
      return
    }
    context.value = result
  } catch (cause) {
    if (request === generation) error.value = cause instanceof Error ? cause.message : '无法读取审核依据'
  } finally { if (request === generation) loading.value = false }
}
function close() { action.value = null; target.value = null; targetContext.value = null }
watch(() => [props.token, props.snapshot.case.case_id, props.snapshot.case.version], (next, previous) => {
  if (previous && (next[0] !== previous[0] || next[1] !== previous[1])) { close(); message.value = '' }
  void reload()
}, { immediate: true })
function begin(kind: ReviewerAction['action']) {
  if (!context.value?.allowed_actions.includes(kind)) return
  target.value = props.snapshot; targetContext.value = context.value
  action.value = kind; reason.value = ''; evidenceIds.value = []; policyIds.value = []; error.value = ''
}
const canSubmit = computed(() => !!reason.value.trim() && (action.value !== 'MANUAL_PROPOSAL'
  || (evidenceIds.value.length > 0 && evidenceIds.value.length <= 20 && policyIds.value.length > 0 && policyIds.value.length <= 10)))
async function submit() {
  if (!target.value || !action.value || !canSubmit.value || submitting.value) return
  const body: ReviewerAction = { action: action.value, reason: reason.value.trim() }
  if (body.action === 'MANUAL_PROPOSAL') {
    body.evidence_refs = availableEvidence.value.filter(item => evidenceIds.value.includes(item.observation_id)).map(item => ({
      observation_id: item.observation_id, source_ref: item.source_ref!, source_version: item.source_version!, content_hash: item.content_hash!,
    }))
    body.policy_refs = targetContext.value!.policy_rules.filter(rule => policyIds.value.includes(key(rule))).map(rule => ({
      bundle_id: rule.bundle_id, version: rule.version, rule_id: rule.rule_id, chunk_id: rule.chunk_id, content_hash: rule.content_hash,
    }))
  }
  submitting.value = true; emit('working', true); error.value = ''; message.value = ''
  let refresh = false
  try {
    await coreApi.reviewerAction(props.token, target.value, body)
    message.value = body.action === 'MANUAL_PROPOSAL' ? '人工方案已提交。请核对服务端生成的待审授权，再作审批决定。'
      : body.action === 'REQUEST_INFO' ? '补证要求已记录，工单等待客户补充材料。' : '已记录拒绝理由，工单已结束。'
    close(); refresh = true
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 409) {
      close(); refresh = true; error.value = '工单已变化或该操作已不可用，已请求刷新。请重新核对后提交。'
    } else error.value = cause instanceof Error ? cause.message : '提交失败'
  } finally { submitting.value = false; emit('working', false); if (refresh) emit('changed') }
}
</script>

<template>
  <section class="detail-section reviewer-workspace" aria-label="人工接管与政策依据">
    <div class="section-heading"><h3>人工接管与政策依据</h3><button class="secondary-button" type="button" :disabled="loading || busy" @click="reload">刷新依据</button></div>
    <p v-if="loading" class="muted">正在读取当前可用操作与绑定政策…</p>
    <p v-if="error && !action" role="alert" class="message error">{{ error }}</p>
    <p v-if="message" role="status" class="message">{{ message }}</p>
    <template v-if="context">
      <p v-if="context.blocked_reason" class="muted">{{ context.blocked_reason }}</p>
      <p v-else class="muted">可根据原始材料和政策形成人工方案。提交方案后仍需单独审批，退款金额由服务端确定。</p>
      <div class="actions handoff-actions">
        <button v-if="context.allowed_actions.includes('MANUAL_PROPOSAL')" type="button" class="secondary-button" :disabled="busy" data-test="manual-proposal" @click="begin('MANUAL_PROPOSAL')">形成人工退款方案</button>
        <button v-if="context.allowed_actions.includes('REQUEST_INFO')" type="button" class="secondary-button" :disabled="busy" data-test="handoff-info" @click="begin('REQUEST_INFO')">要求补充材料</button>
        <button v-if="context.allowed_actions.includes('REJECT')" type="button" class="danger-button" :disabled="busy" data-test="handoff-reject" @click="begin('REJECT')">拒绝申请</button>
      </div>
      <details class="bound-policies"><summary>查看绑定政策原文（{{ context.policy_rules.length }} 条）</summary>
        <p class="muted">这些是本工单绑定版本的政策条款；是否适用仍需结合事实判断。</p>
        <p v-if="!context.policy_rules.length" class="context-warning">暂无可读取的绑定政策，不能据此形成有政策依据的退款方案。</p>
        <article v-for="rule in context.policy_rules" :id="`policy-${rule.rule_id}`" :key="key(rule)" class="policy-text">
          <strong>{{ rule.title }}</strong><small>{{ rule.rule_id }} · {{ rule.bundle_id }} · v{{ rule.version }}</small><p>{{ rule.text }}</p>
        </article>
      </details>
      <div v-if="context.execution && (executionLabels[context.execution.case_status] || context.execution.outcome)" class="execution-result" aria-label="退款执行结果">
        <h4>{{ context.execution.outcome ? outcomeLabels[context.execution.outcome] ?? context.execution.outcome : executionLabels[context.execution.case_status] }}</h4>
        <p v-if="context.execution.case_status === 'RECONCILING' || context.execution.outcome === 'UNKNOWN'">尚未确认最终结果，系统继续核对同一笔退款，请勿重复发起。</p>
        <p v-if="context.execution.amount_minor !== null">退款金额：{{ formatMinorUnits(context.execution.amount_minor, 'CNY') }}</p>
        <p v-if="context.execution.reason_code">原因：{{ context.execution.reason_code }}</p>
        <small v-if="context.execution.operation_id">执行编号：{{ context.execution.operation_id }}</small>
      </div>
      <details v-if="context.review_history?.length" class="bound-policies"><summary>人工决定与补证记录（{{ context.review_history.length }}）</summary>
        <article v-for="(event, index) in context.review_history" :key="index" class="policy-text"><strong>{{ event.reason || '调查需要补充信息，原记录未提供问题正文' }}</strong><small>{{ event.actor || '系统调查' }} · 第 {{ event.revision }} 版 · {{ new Date(event.occurred_at).toLocaleString('zh-CN') }}</small><small v-if="event.question_id">补证问题编号：{{ event.question_id }}</small></article>
      </details>
    </template>
    <ReviewDialog v-if="action && target" :title="labels[action]" :busy="submitting" @close="close">
      <p class="subtle">工单 {{ target.case.case_id }} · 第 {{ target.case.input_revision }} 版材料</p>
      <template v-if="action === 'MANUAL_PROPOSAL'">
        <fieldset class="citation-picker"><legend>选择材料依据</legend>
          <p v-if="!availableEvidence.length" class="context-warning">当前没有包含完整来源信息的材料，请先核对或补充证据。</p>
          <label v-for="item in availableEvidence" :key="item.observation_id"><input v-model="evidenceIds" type="checkbox" :value="item.observation_id" /><span>{{ item.reviewed_evidence_id ? '人工核验' : '原始材料' }}：{{ item.content }}</span></label>
        </fieldset>
        <fieldset class="citation-picker"><legend>选择适用政策</legend>
          <p v-if="!targetContext?.policy_rules.length" class="context-warning">缺少绑定政策，无法提交退款方案。</p>
          <label v-for="rule in targetContext?.policy_rules" :key="key(rule)"><input v-model="policyIds" type="checkbox" :value="key(rule)" /><span><strong>{{ rule.title }}</strong><small>{{ rule.text }}</small></span></label>
        </fieldset>
      </template>
      <label>{{ action === 'REQUEST_INFO' ? '需要补充的材料与原因' : '决定依据与理由' }}<textarea v-model="reason" maxlength="1000" rows="4" /></label>
      <p v-if="error" role="alert" class="message error">{{ error }}</p>
      <div class="dialog-actions"><button class="secondary-button" type="button" :disabled="submitting" @click="close">取消</button><button type="button" data-test="submit-handoff" :disabled="!canSubmit || submitting" @click="submit">{{ submitting ? '正在提交…' : '确认提交' }}</button></div>
    </ReviewDialog>
  </section>
</template>

<style scoped>
.handoff-actions { flex-wrap: wrap; margin: 12px 0; }
.bound-policies { border-top: 1px solid var(--border, #e3eaf4); padding-top: 12px; }
.bound-policies summary { cursor: pointer; color: #125bed; font-weight: 600; }
.policy-text { padding: 12px 0; border-bottom: 1px solid #e8edf5; }
.policy-text small, .citation-picker small { display: block; color: #66758e; margin-top: 5px; }
.policy-text p { white-space: pre-wrap; line-height: 1.7; }
.execution-result { margin: 14px 0; padding: 14px; background: #f1f6ff; border: 1px solid #dbe7fc; border-radius: 8px; overflow-wrap: anywhere; }
.execution-result h4 { margin: 0 0 8px; }
.execution-result small { color: #66758e; }
.citation-picker { margin: 14px 0; padding: 12px; border: 1px solid #dce5f2; border-radius: 8px; max-height: 230px; overflow: auto; }
.citation-picker label { display: flex; flex-direction: row; align-items: flex-start; gap: 9px; margin: 10px 0; }
.citation-picker input { width: 16px; min-width: 16px; margin-top: 3px; }
</style>
