<script setup lang="ts">
/**
 * Manual hand-off, the bound policy text, and the two layers that sit beside it.
 *
 * The policy clause is shown in three layers that must not merge: the **stored text** (the
 * authoritative clause, with limiting phrasing marked as stored), the **Agent's own reading**
 * (labelled as a model summary that is not authority), and the **service's re-check result**
 * (only what Java actually recorded — a proposal status or a refusal reason, never a client-side
 * eligibility calculator). A citation opens the clause it names, which requires the review
 * context: it is loaded once by the parent and passed down, so one request serves the page
 * instead of one per citation.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ApiError, coreApi, type CaseSnapshot, type ReviewContext, type ReviewerAction } from '../client'
import ReviewDialog from './ReviewDialog.vue'
import { formatMinorUnits } from '../money'
import { policyKey, splitPolicySpans } from './investigation-format'

const props = defineProps<{
  token: string
  snapshot: CaseSnapshot
  busy: boolean
  context: ReviewContext | null
  contextLoading?: boolean
  contextError?: string
  /** The five-member identity of a clause a citation asked to open. */
  focusKey?: string | null
  /** Bumped on every request so the same clause can be re-opened. */
  focusNonce?: number
}>()
const emit = defineEmits<{ changed: []; working: [value: boolean] }>()
const message = ref('')
const error = ref('')
const target = ref<CaseSnapshot | null>(null)
const targetContext = ref<ReviewContext | null>(null)
const action = ref<ReviewerAction['action'] | null>(null)
const reason = ref('')
const evidenceIds = ref<string[]>([])
const policyIds = ref<string[]>([])
const submitting = ref(false)
const policiesOpen = ref(false)
const policyNodes = ref<HTMLElement[]>([])
const executionLabels: Record<string, string> = { AUTHORIZED: '已批准，等待执行', EXECUTING: '退款执行中', RECONCILING: '退款结果待确认', CLOSED_SUCCESS: '模拟退款成功' }
const outcomeLabels: Record<string, string> = { SUCCEEDED: '模拟退款成功', FAILED: '退款明确失败', UNKNOWN: '退款结果待确认' }
const labels = { MANUAL_PROPOSAL: '提交人工退款方案', REJECT: '拒绝申请', REQUEST_INFO: '要求补充材料' }
const availableEvidence = computed(() => target.value?.evidence.filter(item => item.source_ref && item.source_version && item.content_hash) ?? [])
const rules = computed(() => props.context?.policy_rules ?? [])
const citedKeys = computed(() => new Set(
  (Array.isArray(props.snapshot.proposal?.policy_refs) ? props.snapshot.proposal!.policy_refs as unknown[] : [])
    .map(reference => policyKey(reference))
    .filter((key): key is string => key !== null),
))
const proposal = computed(() => props.snapshot.proposal as Record<string, unknown> | undefined)
const proposalRevision = computed(() => (typeof proposal.value?.input_revision === 'number' ? proposal.value.input_revision as number : null))
const currentProposal = computed(() => proposalRevision.value !== null && proposalRevision.value === props.snapshot.case.input_revision)
const agentReading = computed(() => (typeof proposal.value?.summary === 'string' ? proposal.value.summary : null))
const revisionProgress = computed(() => {
  const current = props.snapshot.case.input_revision
  const revision = proposalRevision.value
  if (revision !== null && revision < current) return {
    title: `旧版建议（第 ${revision} 版）已失效`,
    detail: props.snapshot.case.status === 'WAITING_CUSTOMER'
      ? `当前为第 ${current} 版，正在等待客户回答补证问题。`
      : props.snapshot.case.status === 'ANALYZING'
        ? `当前为第 ${current} 版，Agent 正在基于新增材料重新调查。`
        : `当前为第 ${current} 版，新调查已排队；生成新建议前不能沿用旧审批。`,
    stale: true,
  }
  if (props.snapshot.case.status === 'QUEUED') return {
    title: `第 ${current} 版调查已排队`, detail: '等待 Agent 接收当前修订；也可继续人工核对并形成人工方案。', stale: false,
  }
  if (props.snapshot.case.status === 'ANALYZING') return {
    title: `正在调查第 ${current} 版材料`, detail: '新结果到达后会形成当前修订的建议，再进入审批。', stale: false,
  }
  if (props.snapshot.case.status === 'WAITING_CUSTOMER') return {
    title: `第 ${current} 版正在等待补证`, detail: '客户回答当前问题后会产生新修订并自动重新调查。', stale: false,
  }
  if (revision === current) return {
    title: `当前建议对应第 ${current} 版`, detail: '请结合原始记录、人工核验和绑定政策后再决定。', stale: false,
  }
  return null
})
const key = (rule: ReviewContext['policy_rules'][number]) => policyKey(rule)
/** A readable prefix, or an explicit 'not recorded' — never a crash on a malformed row. */
const shortHash = (value: unknown) => (typeof value === 'string' && value ? `${value.slice(0, 12)}…` : '未提供')

watch(() => props.focusNonce, async () => {
  const wanted = props.focusKey
  if (!wanted) return
  policiesOpen.value = true
  await nextTick()
  const index = rules.value.findIndex(rule => policyKey(rule) === wanted)
  if (index < 0) return
  const node = policyNodes.value[index]
  // `scrollIntoView` is absent in a detached test tree; the focus move is the part that matters.
  node?.scrollIntoView?.({ block: 'center' })
  node?.querySelector<HTMLElement>('[data-policy-heading]')?.focus()
}, { immediate: true })

watch(() => [props.token, props.snapshot.case.case_id, props.snapshot.case.version], (next, previous) => {
  if (previous && (next[0] !== previous[0] || next[1] !== previous[1])) { close(); message.value = '' }
})
function close() { action.value = null; target.value = null; targetContext.value = null }
function begin(kind: ReviewerAction['action']) {
  if (!props.context?.allowed_actions.includes(kind)) return
  target.value = props.snapshot; targetContext.value = props.context
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
    body.policy_refs = targetContext.value!.policy_rules.filter(rule => policyIds.value.includes(key(rule)!)).map(rule => ({
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
    <div class="section-heading"><h3>人工接管与政策依据</h3></div>
    <div v-if="revisionProgress" class="revision-progress" :class="{ stale: revisionProgress.stale }" data-test="revision-progress">
      <strong>{{ revisionProgress.title }}</strong><span>{{ revisionProgress.detail }}</span>
    </div>
    <p v-if="contextLoading" class="muted">正在读取当前可用操作与绑定政策…</p>
    <p v-if="(contextError || error) && !action" role="alert" class="message error">{{ contextError || error }}</p>
    <p v-if="message" role="status" class="message">{{ message }}</p>
    <template v-if="context">
      <p v-if="context.blocked_reason" class="muted">{{ context.blocked_reason }}</p>
      <p v-else class="muted">可根据原始材料和政策形成人工方案。提交方案后仍需单独审批，退款金额由服务端确定。</p>
      <div class="actions handoff-actions">
        <button v-if="context.allowed_actions.includes('MANUAL_PROPOSAL')" type="button" class="secondary-button" :disabled="busy" data-test="manual-proposal" @click="begin('MANUAL_PROPOSAL')">形成人工退款方案</button>
        <button v-if="context.allowed_actions.includes('REQUEST_INFO')" type="button" class="secondary-button" :disabled="busy" data-test="handoff-info" @click="begin('REQUEST_INFO')">要求补充材料</button>
        <button v-if="context.allowed_actions.includes('REJECT')" type="button" class="danger-button" :disabled="busy" data-test="handoff-reject" @click="begin('REJECT')">拒绝申请</button>
      </div>

      <div class="policy-layers" aria-label="政策依据的三个层次">
        <div class="policy-layer">
          <h4>① 原始条款（权威文本）</h4>
          <p class="muted">以下是本工单绑定版本的政策原文；标出的是原文本身含限制性表述的句子，不是解释。</p>
        </div>
        <div class="policy-layer">
          <h4>② Agent 解释与适用判断</h4>
          <p v-if="agentReading && currentProposal" class="policy-agent" data-test="agent-reading">{{ agentReading }}</p>
          <p v-else-if="agentReading" class="policy-agent stale" data-test="agent-reading">旧版建议（第 {{ proposalRevision }} 版）的解释：{{ agentReading }}——已失效，仅供比对。</p>
          <p v-else class="muted">本工单当前没有 Agent 方案，因此没有模型解释；人工方案的理由在提交记录中。</p>
        </div>
        <div class="policy-layer">
          <h4>③ 服务端复核结果</h4>
          <p v-if="proposal?.status" data-test="server-recheck">方案状态：{{ proposal.status }}<span v-if="proposal.refusal_reason"> · 复核未通过：{{ proposal.refusal_reason }}</span></p>
          <p v-else class="muted">服务端尚无方案复核结果。</p>
          <p class="muted">资格与金额由服务端判定；本页不计算退款资格。</p>
        </div>
      </div>

      <details class="bound-policies" :open="policiesOpen" @toggle="policiesOpen = ($event.target as HTMLDetailsElement).open">
        <summary>查看绑定政策原文（{{ rules.length }} 条）</summary>
        <p class="muted">这些是本工单绑定版本的政策条款；是否适用仍需结合事实判断。</p>
        <p v-if="!rules.length" class="context-warning">暂无可读取的绑定政策，不能据此形成有政策依据的退款方案。</p>
        <article v-for="(rule, index) in rules" :id="`bound-policy-${index}`" :key="key(rule) ?? index"
          :ref="element => { if (element) policyNodes[index] = element as HTMLElement }" class="policy-text" data-test="bound-policy">
          <h4 data-policy-heading tabindex="-1">{{ rule.title }}</h4>
          <small>{{ rule.rule_id }} · {{ rule.bundle_id }} · v{{ rule.version }} · {{ rule.chunk_id }} · 摘要 {{ shortHash(rule.content_hash) }}</small>
          <p v-if="key(rule) && citedKeys.has(key(rule)!)" class="policy-cited" data-test="policy-cited">本方案引用此条款</p>
          <div class="policy-raw">
            <p v-for="(span, spanIndex) in splitPolicySpans(rule.text)" :key="spanIndex" :class="{ limiting: span.limiting }"
              :data-limiting="span.limiting ? 'true' : undefined">{{ span.text }}</p>
          </div>
          <p v-if="splitPolicySpans(rule.text).some(span => span.limiting)" class="policy-note">
            原文含限制性表述（如"例外/除外/但/不得"），已按原文标出；是否适用由人判断，本页不作推断。
          </p>
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
          <label v-for="(rule, index) in (targetContext?.policy_rules ?? [])" :key="key(rule) ?? index"><input v-model="policyIds" type="checkbox" :value="key(rule)" /><span><strong>{{ rule.title }}</strong><small>{{ rule.text }}</small></span></label>
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
.revision-progress { display: grid; gap: 4px; margin: 12px 0; padding: 12px 14px; border: 1px solid #cfe0fb; border-radius: 8px; background: #f3f7ff; color: #24456f; }
.revision-progress.stale { border-color: #f1cf91; background: #fff8e9; color: #704d13; }
.revision-progress span { font-size: 13px; line-height: 1.55; }
.policy-layers { display: grid; gap: 10px; margin: 14px 0; }
.policy-layer { padding: 10px 12px; border: 1px solid #e3eaf4; border-radius: 8px; background: #fbfcfe; }
.policy-layer h4 { margin: 0 0 6px; font-size: 13px; color: #24456f; }
.policy-layer p { margin: 0; font-size: 13px; line-height: 1.65; }
.policy-agent { white-space: pre-wrap; color: #33445c; }
.policy-agent.stale { color: #8a4b12; }
.bound-policies { border-top: 1px solid var(--border, #e3eaf4); padding-top: 12px; }
.bound-policies summary { cursor: pointer; color: #125bed; font-weight: 600; }
.policy-text { padding: 12px 0; border-bottom: 1px solid #e8edf5; }
.policy-text h4 { margin: 0 0 4px; font-size: 14px; }
.policy-text h4:focus-visible { outline: 2px solid #165dff; outline-offset: 2px; border-radius: 4px; }
.policy-text small, .citation-picker small { display: block; color: #66758e; margin-top: 5px; overflow-wrap: anywhere; }
.policy-raw p { white-space: pre-wrap; line-height: 1.7; margin: 6px 0; }
.policy-raw p.limiting { border-left: 3px solid #e6a23c; background: #fffaf0; padding-left: 8px; }
.policy-note { font-size: 12px; color: #8a4b12; margin: 6px 0 0; }
.policy-cited { display: inline-block; font-size: 12px; color: #165dff; background: #eef4ff; border-radius: 999px; padding: 2px 8px; }
.execution-result { margin: 14px 0; padding: 14px; background: #f1f6ff; border: 1px solid #dbe7fc; border-radius: 8px; overflow-wrap: anywhere; }
.execution-result h4 { margin: 0 0 8px; }
.execution-result small { color: #66758e; }
.citation-picker { margin: 14px 0; padding: 12px; border: 1px solid #dce5f2; border-radius: 8px; max-height: 230px; overflow: auto; }
.citation-picker label { display: flex; flex-direction: row; align-items: flex-start; gap: 9px; margin: 10px 0; }
.citation-picker input { width: 16px; min-width: 16px; margin-top: 3px; }
</style>
